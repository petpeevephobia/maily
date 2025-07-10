# Gunicorn configuration file
import multiprocessing

# Server socket
bind = "0.0.0.0:10000"
backlog = 2048

# Worker processes
workers = 1  # Use only 1 worker to minimize memory usage
worker_class = 'sync'
worker_connections = 1000
timeout = 600  # Increased from 30 to 300 seconds (5 minutes)
keepalive = 2

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Process naming
proc_name = 'maily'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL
keyfile = None
certfile = None 