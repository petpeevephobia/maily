FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set environment variables
# ENV PORT 5000
# EXPOSE 5000
# replace the shell‐form CMD with an exec‐form ENTRYPOINT
ENTRYPOINT ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]

# Start the web server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"] 