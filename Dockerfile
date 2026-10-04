# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY web/frontend/package*.json ./
RUN npm install
COPY web/frontend/ ./
RUN npm run build

# Stage 2: Build the Python backend
FROM python:3.10-slim
WORKDIR /app

# Install system dependencies for Pillow and send2trash
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Using a requirements inline since it's short
RUN pip install --no-cache-dir fastapi uvicorn pydantic pillow send2trash requests

# Copy backend source
COPY web/backend/ /app/web/backend/

# Copy the scanner.py which is required by backend
COPY scanner.py /app/

# Copy the built frontend static files from the builder stage
COPY --from=frontend-builder /app/frontend/dist /app/web/frontend/dist

# Expose the API port
EXPOSE 8000

# Run the FastAPI server via uvicorn directly
WORKDIR /app/web/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
