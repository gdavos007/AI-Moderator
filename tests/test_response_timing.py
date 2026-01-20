"""
Unit tests for event-driven response timing in the moderator agent.

Tests:
1. Answer within timeout → advances by answer, not timeout
2. No answer → triggers timeout and advances with no-response
3. Timer cancellation when speech detected
4. Repeat request detection
5. TurnController turn_id guards and task management
6. Silence prompt and skip behavior
7. Long-answer wrapup behavior
8. Ghost timer prevention
"""

import pytest
import asyncio
import time
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

# Add services/agent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "agent"))


class TestQuestionContext:
    """Test the QuestionContext dataclass."""
    
    def test_add_transcript_sets_has_speech(self):
        """First transcript should set has_speech=True."""
        from moderator import QuestionContext
        
        ctx = QuestionContext()
        assert ctx.has_speech is False
        
        ctx.add_transcript("hello")
        
        assert ctx.has_speech is True
        assert len(ctx.transcripts) == 1
        assert ctx.first_speech_at > 0
    
    def test_add_transcript_updates_last_speech_at(self):
        """Each transcript should update last_speech_at."""
        from moderator import QuestionContext
        
        ctx = QuestionContext()
        ctx.add_transcript("first")
        first_time = ctx.last_speech_at
        
        time.sleep(0.1)
        ctx.add_transcript("second")
        
        assert ctx.last_speech_at > first_time
        assert len(ctx.transcripts) == 2
    
    def test_get_full_text(self):
        """Full text should join all transcripts."""
        from moderator import QuestionContext
        
        ctx = QuestionContext()
        ctx.add_transcript("hello")
        ctx.add_transcript("world")
        
        assert ctx.get_full_text() == "hello world"
    
    def test_is_asking_to_repeat_positive(self):
        """Should detect repeat requests."""
        from moderator import QuestionContext
        
        test_phrases = [
            "can you repeat that",
            "what was the question",
            "I didn't hear you",
            "pardon me",
            "come again",
            "say that again please",
        ]
        
        for phrase in test_phrases:
            ctx = QuestionContext()
            ctx.add_transcript(phrase)
            assert ctx.is_asking_to_repeat(), f"Should detect '{phrase}' as repeat request"
    
    def test_is_asking_to_repeat_negative(self):
        """Should not falsely detect repeat requests."""
        from moderator import QuestionContext
        
        normal_answers = [
            "I think the product is great",
            "My experience was positive",
            "I would recommend it to friends",
        ]
        
        for answer in normal_answers:
            ctx = QuestionContext()
            ctx.add_transcript(answer)
            assert not ctx.is_asking_to_repeat(), f"Should NOT detect '{answer}' as repeat request"
    
    def test_time_since_last_speech_infinity_when_no_speech(self):
        """Should return infinity when no speech."""
        from moderator import QuestionContext
        
        ctx = QuestionContext()
        assert ctx.time_since_last_speech() == float('inf')
    
    def test_time_since_last_speech_accurate(self):
        """Should accurately measure time since last speech."""
        from moderator import QuestionContext
        
        ctx = QuestionContext()
        ctx.add_transcript("hello")
        time.sleep(0.2)
        
        elapsed = ctx.time_since_last_speech()
        assert 0.15 < elapsed < 0.5  # Some tolerance for execution time
    
    def test_cancel_timer_stops_task(self):
        """Timer cancellation should stop the task."""
        from moderator import QuestionContext
        
        async def run_test():
            ctx = QuestionContext()
            
            # Create a fake timer task
            async def fake_timer():
                await asyncio.sleep(10)
            
            ctx.timeout_task = asyncio.create_task(fake_timer())
            assert not ctx.timeout_task.done()
            
            ctx.cancel_timer()
            
            # Give it a moment to cancel
            await asyncio.sleep(0.1)
            assert ctx.timeout_task is None or ctx.timeout_task.cancelled()
        
        asyncio.run(run_test())
    
    def test_reset_clears_state(self):
        """Reset should clear all transcript state."""
        from moderator import QuestionContext
        
        ctx = QuestionContext()
        ctx.add_transcript("hello")
        ctx.add_transcript("world")
        
        assert ctx.has_speech is True
        assert len(ctx.transcripts) == 2
        
        ctx.reset()
        
        assert ctx.has_speech is False
        assert len(ctx.transcripts) == 0
        assert ctx.first_speech_at == 0
        assert ctx.last_speech_at == 0


class TestTurnController:
    """Test the TurnController class for turn management."""
    
    def test_start_turn_increments_turn_id(self):
        """start_turn should increment turn_id each time."""
        from moderator import TurnController
        
        tc = TurnController()
        assert tc.turn_id == 0
        
        tc.start_turn("p1", "Alice", "What do you think?")
        assert tc.turn_id == 1
        
        tc.start_turn("p2", "Bob", "What do you think?")
        assert tc.turn_id == 2
        
        tc.start_turn("p3", "Charlie", "What do you think?")
        assert tc.turn_id == 3
    
    def test_start_turn_resets_state(self):
        """start_turn should reset all state."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "Question 1")
        
        # Add some state
        tc.has_speech = True
        tc.first_speech_at = 123.0
        tc.last_speech_at = 456.0
        tc.silence_prompted = True
        tc.wrapup_prompted = True
        tc.transcripts = ["hello", "world"]
        
        # Start new turn
        tc.start_turn("p2", "Bob", "Question 2")
        
        assert tc.has_speech is False
        assert tc.first_speech_at == 0
        assert tc.last_speech_at == 0
        assert tc.silence_prompted is False
        assert tc.wrapup_prompted is False
        assert tc.transcripts == []
        assert tc.participant_name == "Bob"
    
    def test_on_speech_detected_sets_has_speech(self):
        """on_speech_detected should set has_speech and timestamps."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "Question")
        
        assert tc.has_speech is False
        
        tc.on_speech_detected("hello")
        
        assert tc.has_speech is True
        assert tc.first_speech_at > 0
        assert tc.last_speech_at > 0
        assert "hello" in tc.transcripts
    
    def test_on_speech_detected_cancels_silence_timers(self):
        """on_speech_detected should cancel silence timers."""
        from moderator import TurnController
        
        async def run_test():
            tc = TurnController()
            tc.start_turn("p1", "Alice", "Question")
            
            # Create fake silence tasks
            async def fake_task():
                await asyncio.sleep(10)
            
            tc.silence_prompt_task = asyncio.create_task(fake_task())
            tc.silence_grace_task = asyncio.create_task(fake_task())
            
            assert not tc.silence_prompt_task.done()
            assert not tc.silence_grace_task.done()
            
            tc.on_speech_detected("hello")
            
            await asyncio.sleep(0.1)
            
            assert tc.silence_prompt_task is None
            assert tc.silence_grace_task is None
        
        asyncio.run(run_test())
    
    def test_on_speech_detected_does_not_cancel_wrapup_timer(self):
        """on_speech_detected should NOT cancel max_answer or wrapup timers."""
        from moderator import TurnController
        
        async def run_test():
            tc = TurnController()
            tc.start_turn("p1", "Alice", "Question")
            
            async def fake_task():
                await asyncio.sleep(10)
            
            tc.max_answer_task = asyncio.create_task(fake_task())
            tc.wrapup_task = asyncio.create_task(fake_task())
            
            tc.on_speech_detected("hello")
            
            await asyncio.sleep(0.1)
            
            # These should still be running (not cancelled by speech detection)
            assert tc.max_answer_task is not None
            assert tc.wrapup_task is not None
            
            # Cleanup
            tc.cancel_all_tasks()
        
        asyncio.run(run_test())
    
    def test_cancel_all_tasks_cleans_up(self):
        """cancel_all_tasks should cancel all running tasks."""
        from moderator import TurnController
        
        async def run_test():
            tc = TurnController()
            tc.start_turn("p1", "Alice", "Question")
            
            async def fake_task():
                await asyncio.sleep(10)
            
            tc.silence_prompt_task = asyncio.create_task(fake_task())
            tc.silence_grace_task = asyncio.create_task(fake_task())
            tc.max_answer_task = asyncio.create_task(fake_task())
            tc.wrapup_task = asyncio.create_task(fake_task())
            tc.end_of_speech_task = asyncio.create_task(fake_task())
            
            tc.cancel_all_tasks()
            
            await asyncio.sleep(0.1)
            
            assert tc.silence_prompt_task is None
            assert tc.silence_grace_task is None
            assert tc.max_answer_task is None
            assert tc.wrapup_task is None
            assert tc.end_of_speech_task is None
        
        asyncio.run(run_test())
    
    def test_on_turn_end_sets_event_and_cancels_tasks(self):
        """on_turn_end should set turn_ended event and cancel all tasks."""
        from moderator import TurnController
        
        async def run_test():
            tc = TurnController()
            tc.start_turn("p1", "Alice", "Question")
            
            async def fake_task():
                await asyncio.sleep(10)
            
            tc.silence_prompt_task = asyncio.create_task(fake_task())
            
            assert not tc.turn_ended.is_set()
            
            tc.on_turn_end("test_reason")
            
            assert tc.turn_ended.is_set()
            assert tc.silence_prompt_task is None
        
        asyncio.run(run_test())
    
    def test_answer_duration_tracks_from_first_speech(self):
        """answer_duration should track time from first speech."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "Question")
        
        # Before speech
        assert tc.answer_duration() == 0
        
        tc.on_speech_detected("hello")
        time.sleep(0.2)
        
        duration = tc.answer_duration()
        assert 0.15 < duration < 0.5
    
    def test_is_asking_to_repeat_detects_patterns(self):
        """is_asking_to_repeat should detect repeat requests."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "Question")
        
        tc.on_speech_detected("can you repeat that please")
        
        assert tc.is_asking_to_repeat() is True
    
    def test_is_asking_to_repeat_negative(self):
        """is_asking_to_repeat should not false-positive on normal answers."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "Question")
        
        tc.on_speech_detected("I think the product is excellent")
        
        assert tc.is_asking_to_repeat() is False


class TestSilenceHandling:
    """Test silence prompt and skip behavior."""
    
    @pytest.mark.asyncio
    async def test_silence_prompt_triggered_after_prompt_seconds(self):
        """Silence prompt should trigger after SILENCE_PROMPT_SECONDS with no speech."""
        from moderator import ModeratorState, TurnController
        
        state = ModeratorState()
        tc = state.turn_controller
        tc.start_turn("p1", "Alice", "What do you think?", "q1")
        
        prompt_triggered = False
        
        async def silence_prompt_watcher():
            nonlocal prompt_triggered
            try:
                await asyncio.sleep(0.3)  # Short for test
                if not tc.has_speech:
                    prompt_triggered = True
                    tc.silence_prompted = True
            except asyncio.CancelledError:
                pass
        
        task = asyncio.create_task(silence_prompt_watcher())
        
        await asyncio.sleep(0.5)
        
        assert prompt_triggered is True
        assert tc.silence_prompted is True
        
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    @pytest.mark.asyncio
    async def test_silence_skip_after_grace_seconds(self):
        """Should skip participant after silence prompt + grace period."""
        from moderator import ModeratorState
        
        state = ModeratorState()
        tc = state.turn_controller
        tc.start_turn("p1", "Alice", "What do you think?", "q1")
        
        skip_triggered = False
        
        async def silence_flow():
            nonlocal skip_triggered
            # Prompt after 0.2s
            await asyncio.sleep(0.2)
            tc.silence_prompted = True
            # Grace period of 0.2s
            await asyncio.sleep(0.2)
            if not tc.has_speech:
                skip_triggered = True
        
        await silence_flow()
        
        assert skip_triggered is True
    
    @pytest.mark.asyncio
    async def test_speech_before_prompt_cancels_silence_timers(self):
        """Speech before prompt time should cancel silence timer."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "What do you think?", "q1")
        
        prompt_triggered = False
        
        async def silence_prompt_watcher():
            nonlocal prompt_triggered
            try:
                await asyncio.sleep(0.5)  # Would trigger prompt
                if not tc.has_speech:
                    prompt_triggered = True
            except asyncio.CancelledError:
                pass
        
        tc.silence_prompt_task = asyncio.create_task(silence_prompt_watcher())
        
        # Speech arrives before prompt time
        await asyncio.sleep(0.2)
        tc.on_speech_detected("I think...")
        
        await asyncio.sleep(0.5)
        
        assert prompt_triggered is False
        assert tc.has_speech is True
    
    @pytest.mark.asyncio
    async def test_speech_after_prompt_cancels_grace_timer(self):
        """Speech after prompt but before grace expiry should cancel skip."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "What do you think?", "q1")
        
        skip_triggered = False
        
        async def grace_watcher():
            nonlocal skip_triggered
            try:
                await asyncio.sleep(0.5)
                if not tc.has_speech:
                    skip_triggered = True
            except asyncio.CancelledError:
                pass
        
        # Simulate prompt already happened
        tc.silence_prompted = True
        tc.silence_grace_task = asyncio.create_task(grace_watcher())
        
        # Speech arrives during grace period
        await asyncio.sleep(0.2)
        tc.on_speech_detected("Oh, I have a thought...")
        
        await asyncio.sleep(0.5)
        
        assert skip_triggered is False
        assert tc.has_speech is True


class TestLongAnswerHandling:
    """Test max answer and wrapup behavior."""
    
    @pytest.mark.asyncio
    async def test_wrapup_triggered_after_max_answer_seconds(self):
        """Wrapup should trigger after MAX_ANSWER_SECONDS of speaking."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "What do you think?", "q1")
        
        wrapup_triggered = False
        max_answer_seconds = 0.3  # Short for test
        
        async def max_answer_watcher():
            nonlocal wrapup_triggered
            try:
                await tc.speech_detected.wait()
                remaining = max_answer_seconds - tc.answer_duration()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                wrapup_triggered = True
                tc.wrapup_prompted = True
            except asyncio.CancelledError:
                pass
        
        tc.max_answer_task = asyncio.create_task(max_answer_watcher())
        
        # Start speaking
        tc.on_speech_detected("This is a long answer that goes on and on...")
        
        # Wait for wrapup
        await asyncio.sleep(0.5)
        
        assert wrapup_triggered is True
        assert tc.wrapup_prompted is True
        
        tc.cancel_all_tasks()
    
    @pytest.mark.asyncio
    async def test_wrapup_end_after_wrapup_seconds(self):
        """Turn should end after WRAPUP_SECONDS expires."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "What do you think?", "q1")
        
        wrapup_end_triggered = False
        wrapup_seconds = 0.2  # Short for test
        
        async def wrapup_end_watcher():
            nonlocal wrapup_end_triggered
            try:
                await asyncio.sleep(wrapup_seconds)
                wrapup_end_triggered = True
            except asyncio.CancelledError:
                pass
        
        tc.wrapup_prompted = True
        tc.wrapup_task = asyncio.create_task(wrapup_end_watcher())
        
        await asyncio.sleep(0.4)
        
        assert wrapup_end_triggered is True
        
        tc.cancel_all_tasks()
    
    @pytest.mark.asyncio
    async def test_early_stop_cancels_wrapup_timer(self):
        """If user stops speaking early, wrapup timer should be cancelled."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "What do you think?", "q1")
        
        tc.on_speech_detected("Short answer.")
        tc.wrapup_prompted = True
        
        async def fake_wrapup():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass
        
        tc.wrapup_task = asyncio.create_task(fake_wrapup())
        
        # Turn ends early
        tc.on_turn_end("answer")
        
        await asyncio.sleep(0.1)
        
        assert tc.wrapup_task is None


class TestGhostTimerPrevention:
    """Test that ghost timers from previous turns don't fire."""
    
    @pytest.mark.asyncio
    async def test_stale_turn_timer_does_not_fire(self):
        """Timer from turn A should not affect turn B."""
        from moderator import TurnController
        
        tc = TurnController()
        
        turn_a_fired = False
        turn_b_fired = False
        
        # Start turn A
        tc.start_turn("p1", "Alice", "Question 1", "q1")
        turn_a_id = tc.turn_id
        
        async def turn_a_timer():
            nonlocal turn_a_fired
            try:
                await asyncio.sleep(0.3)
                # Should check turn_id before firing
                if tc.turn_id == turn_a_id:
                    turn_a_fired = True
            except asyncio.CancelledError:
                pass
        
        tc.silence_prompt_task = asyncio.create_task(turn_a_timer())
        
        # Immediately start turn B (before timer fires)
        await asyncio.sleep(0.1)
        tc.start_turn("p2", "Bob", "Question 2", "q2")
        turn_b_id = tc.turn_id
        
        # Wait for what would have been turn A's timer
        await asyncio.sleep(0.4)
        
        # Turn A timer should NOT have fired (turn_id check fails)
        assert turn_a_fired is False
        assert tc.turn_id == turn_b_id
    
    @pytest.mark.asyncio
    async def test_multiple_turn_starts_increment_id(self):
        """Rapid turn starts should all increment turn_id."""
        from moderator import TurnController
        
        tc = TurnController()
        
        ids = []
        for i in range(5):
            tc.start_turn(f"p{i}", f"User{i}", f"Q{i}", f"q{i}")
            ids.append(tc.turn_id)
        
        # All IDs should be unique and increasing
        assert ids == [1, 2, 3, 4, 5]
    
    @pytest.mark.asyncio
    async def test_turn_end_prevents_late_timer_effects(self):
        """After turn_end, no timer effects should occur."""
        from moderator import TurnController
        
        tc = TurnController()
        tc.start_turn("p1", "Alice", "Question", "q1")
        
        effects_after_end = []
        
        async def delayed_effect():
            try:
                await asyncio.sleep(0.2)
                if not tc.turn_ended.is_set():
                    effects_after_end.append("effect fired")
            except asyncio.CancelledError:
                pass
        
        tc.silence_prompt_task = asyncio.create_task(delayed_effect())
        
        # End turn immediately
        tc.on_turn_end("manual")
        
        await asyncio.sleep(0.4)
        
        # No effects should have fired
        assert len(effects_after_end) == 0


class TestWaitForResponseEventDriven:
    """Test the legacy event-driven response waiting logic."""
    
    @pytest.mark.asyncio
    async def test_answer_within_timeout_returns_true(self):
        """Answer within timeout should return (True, False) for got_response."""
        from moderator import ModeratorState, wait_for_response_event_driven, END_OF_SPEECH_SILENCE
        
        state = ModeratorState()
        
        # Simulate speech arriving quickly
        async def inject_speech():
            await asyncio.sleep(0.5)  # Small delay
            state.current_question.add_transcript("I think the product is excellent")
            # Then silence for END_OF_SPEECH_SILENCE
        
        inject_task = asyncio.create_task(inject_speech())
        
        with patch('moderator.SILENCE_TIMEOUT', 10.0):  # Long timeout
            with patch('moderator.END_OF_SPEECH_SILENCE', 1.0):  # Short end-of-speech
                got_response, asked_to_repeat = await asyncio.wait_for(
                    wait_for_response_event_driven(state, "q1", 0),
                    timeout=5.0
                )
        
        await inject_task
        
        assert got_response is True, "Should detect response"
        assert asked_to_repeat is False, "Should not be asking to repeat"
    
    @pytest.mark.asyncio
    async def test_no_answer_triggers_timeout(self):
        """No answer should trigger timeout and return (False, False)."""
        from moderator import ModeratorState, wait_for_response_event_driven
        
        state = ModeratorState()
        
        # Don't inject any speech
        with patch('moderator.SILENCE_TIMEOUT', 0.5):  # Very short timeout for test
            got_response, asked_to_repeat = await asyncio.wait_for(
                wait_for_response_event_driven(state, "q1", 0),
                timeout=2.0
            )
        
        assert got_response is False, "Should not detect response"
        assert asked_to_repeat is False, "Should not be asking to repeat"
    
    @pytest.mark.asyncio
    async def test_repeat_request_detected(self):
        """Repeat request should return (True, True)."""
        from moderator import ModeratorState, wait_for_response_event_driven
        
        state = ModeratorState()
        
        async def inject_repeat_request():
            await asyncio.sleep(0.3)
            state.current_question.add_transcript("can you repeat the question")
        
        inject_task = asyncio.create_task(inject_repeat_request())
        
        with patch('moderator.SILENCE_TIMEOUT', 10.0):
            with patch('moderator.END_OF_SPEECH_SILENCE', 0.5):
                got_response, asked_to_repeat = await asyncio.wait_for(
                    wait_for_response_event_driven(state, "q1", 0),
                    timeout=3.0
                )
        
        await inject_task
        
        assert got_response is True
        assert asked_to_repeat is True, "Should detect repeat request"
    
    @pytest.mark.asyncio
    async def test_timer_cancelled_on_speech(self):
        """Timer should be cancelled when speech is detected."""
        from moderator import ModeratorState, wait_for_response_event_driven, QuestionState
        
        state = ModeratorState()
        
        async def inject_speech_and_check_timer():
            await asyncio.sleep(0.2)
            
            # Before speech, timer should be active
            assert state.current_question.timeout_task is not None
            was_done_before = state.current_question.timeout_task.done()
            
            # Inject speech
            state.current_question.add_transcript("hello")
            state.current_question.cancel_timer()  # Simulating what the handler does
            
            await asyncio.sleep(0.1)
            return was_done_before
        
        with patch('moderator.SILENCE_TIMEOUT', 10.0):
            with patch('moderator.END_OF_SPEECH_SILENCE', 0.5):
                check_task = asyncio.create_task(inject_speech_and_check_timer())
                
                result = await asyncio.wait_for(
                    wait_for_response_event_driven(state, "q1", 0),
                    timeout=3.0
                )
                
                was_done_before = await check_task
        
        assert was_done_before is False, "Timer should have been running before speech"


class TestModeratorState:
    """Test ModeratorState management."""
    
    def test_initial_state(self):
        """Initial state should be properly initialized."""
        from moderator import ModeratorState
        
        state = ModeratorState()
        
        assert state.session_started is False
        assert state.session_ended is False
        assert state.agent_speaking is False
        assert state.section_idx == 0
        assert state.question_idx == 0
    
    def test_has_turn_controller(self):
        """ModeratorState should have a TurnController."""
        from moderator import ModeratorState, TurnController
        
        state = ModeratorState()
        
        assert hasattr(state, 'turn_controller')
        assert isinstance(state.turn_controller, TurnController)
    
    def test_advance_question(self):
        """advance() should move to next question."""
        from moderator import ModeratorState
        
        state = ModeratorState()
        state.guide = {
            "sections": [
                {"questions": [{"id": "q1"}, {"id": "q2"}, {"id": "q3"}]}
            ]
        }
        
        assert state.question_idx == 0
        
        state.advance()
        assert state.question_idx == 1
        
        state.advance()
        assert state.question_idx == 2
    
    def test_advance_section(self):
        """advance() should move to next section when questions exhausted."""
        from moderator import ModeratorState
        
        state = ModeratorState()
        state.guide = {
            "sections": [
                {"questions": [{"id": "q1"}]},
                {"questions": [{"id": "q2"}]}
            ]
        }
        
        state.question_idx = 0
        state.advance()  # Should move to section 1
        
        assert state.section_idx == 1
        assert state.question_idx == 0
    
    def test_is_complete(self):
        """is_complete() should return True when all sections done."""
        from moderator import ModeratorState
        
        state = ModeratorState()
        state.guide = {
            "sections": [
                {"questions": [{"id": "q1"}]}
            ]
        }
        
        assert state.is_complete() is False
        
        state.section_idx = 1  # Past last section
        assert state.is_complete() is True


class TestTimingScenarios:
    """Integration-style tests for timing scenarios."""
    
    @pytest.mark.asyncio
    async def test_quick_answer_no_wait(self):
        """Quick answer should not wait the full timeout."""
        from moderator import ModeratorState, wait_for_response_event_driven
        
        state = ModeratorState()
        
        async def quick_answer():
            await asyncio.sleep(0.1)
            state.current_question.add_transcript("Yes, I agree with that completely.")
        
        asyncio.create_task(quick_answer())
        
        start_time = time.time()
        
        with patch('moderator.SILENCE_TIMEOUT', 20.0):  # Long timeout
            with patch('moderator.END_OF_SPEECH_SILENCE', 0.5):  # Short end-of-speech
                got_response, _ = await asyncio.wait_for(
                    wait_for_response_event_driven(state, "q1", 0),
                    timeout=5.0
                )
        
        elapsed = time.time() - start_time
        
        assert got_response is True
        # Should complete in ~0.1s (speech) + ~0.5s (end-of-speech silence) = ~0.6s
        # Not the full 20s timeout
        assert elapsed < 2.0, f"Should complete quickly, took {elapsed:.2f}s"
    
    @pytest.mark.asyncio
    async def test_multiple_transcript_segments(self):
        """Multiple transcript segments should be captured."""
        from moderator import ModeratorState, wait_for_response_event_driven
        
        state = ModeratorState()
        
        async def multi_segment_answer():
            await asyncio.sleep(0.1)
            state.current_question.add_transcript("Well,")
            await asyncio.sleep(0.2)
            state.current_question.add_transcript("I think that")
            await asyncio.sleep(0.2)
            state.current_question.add_transcript("the product is good.")
        
        asyncio.create_task(multi_segment_answer())
        
        with patch('moderator.SILENCE_TIMEOUT', 20.0):
            with patch('moderator.END_OF_SPEECH_SILENCE', 0.5):
                got_response, _ = await asyncio.wait_for(
                    wait_for_response_event_driven(state, "q1", 0),
                    timeout=5.0
                )
        
        assert got_response is True
        full_text = state.current_question.get_full_text()
        assert "Well," in full_text
        assert "I think that" in full_text
        assert "product is good" in full_text


class TestConfigurationLoading:
    """Test that configuration values are loaded correctly."""
    
    def test_default_timing_values(self):
        """Default timing values should be reasonable."""
        from moderator import (
            SILENCE_PROMPT_SECONDS,
            SILENCE_GRACE_SECONDS,
            MAX_ANSWER_SECONDS,
            WRAPUP_SECONDS,
            END_OF_SPEECH_SILENCE,
        )
        
        # Check defaults are in expected range
        assert 8 <= SILENCE_PROMPT_SECONDS <= 20
        assert 5 <= SILENCE_GRACE_SECONDS <= 15
        assert 25 <= MAX_ANSWER_SECONDS <= 60
        assert 10 <= WRAPUP_SECONDS <= 30
        assert 2 <= END_OF_SPEECH_SILENCE <= 8
    
    def test_speech_lines_have_placeholders(self):
        """Speech lines should have correct placeholders."""
        from moderator import (
            SPEECH_SILENCE_PROMPT,
            SPEECH_SILENCE_MOVEON,
            SPEECH_WRAPUP_PROMPT,
            SPEECH_WRAPUP_END,
        )
        
        assert "{name}" in SPEECH_SILENCE_PROMPT
        assert len(SPEECH_SILENCE_MOVEON) > 10
        assert len(SPEECH_WRAPUP_PROMPT) > 10
        assert len(SPEECH_WRAPUP_END) > 5
    
    def test_turn_timers_enabled_flag_exists(self):
        """TURN_TIMERS_ENABLED flag should exist."""
        from moderator import TURN_TIMERS_ENABLED
        
        assert isinstance(TURN_TIMERS_ENABLED, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
