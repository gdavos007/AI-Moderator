.PHONY: install dev dev-web dev-api dev-agent test clean

# Install all dependencies
install:
	@echo "=== Installing Python dependencies ==="
	pip install fastapi uvicorn pydantic livekit-api python-dotenv pytest httpx aiohttp livekit-agents livekit-plugins-openai livekit-plugins-deepgram livekit-plugins-silero
	@echo ""
	@echo "=== Installing web dependencies ==="
	cd apps/web && npm install
	@echo ""
	@echo "=== Installation complete! ==="
	@echo "Run 'make dev-api' in one terminal"
	@echo "Run 'make dev-web' in another terminal"

# Run API server only
dev-api:
	@echo "Starting API server on http://localhost:8000..."
	cd services/api && python main.py

# Run web UI only  
dev-web:
	@echo "Starting Web UI on http://localhost:5173..."
	cd apps/web && npm run dev

# Run agent (connects to LiveKit room)
dev-agent:
	@echo "Starting AI Moderator agent..."
	python services/agent/moderator.py dev

# Run all tests
test:
	@echo "Running tests..."
	cd apps/web && npm test || true

# Clean build artifacts
clean:
	rm -rf apps/web/.next apps/web/dist
	rm -rf apps/web/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
