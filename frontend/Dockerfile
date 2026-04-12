FROM node:18-slim

WORKDIR /app

# Install dependencies first for caching
COPY package.json package-lock.json* ./
RUN npm install

# Copy application code
COPY . .

# Expose Vite port
EXPOSE 5173

# Start Vite dev server with --host to allow external access
CMD ["npm", "run", "dev", "--", "--host"]
