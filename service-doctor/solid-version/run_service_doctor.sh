#!/bin/bash
set -e

# Configuration
VENV_DIR="./venv"
REQUIREMENTS_FILE="requirements.txt"
SCRIPT="main.py"
DOCKER_COMPOSE_FILE="docker-compose.yml"
PID_FILE="./app.pid"
LOG_FILE="./service_doctor.log"

# Function to check prerequisites
check_prerequisites() {
    echo "🔍 Checking prerequisites..."
    
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python 3 is not installed. Please install Python 3. Please run: ./prepare_env.sh"
        exit 1
    fi
    
    if ! command -v pip3 &> /dev/null; then
        echo "❌ pip3 is not installed. Please install pip. Please run: ./prepare_env.sh"
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        echo "❌ Docker is not installed. Please run: ./prepare_env.sh"
        exit 1
    fi
    
    if ! docker compose version &> /dev/null && ! docker-compose version &> /dev/null; then
        echo "❌ Docker Compose is not installed. Please run: ./prepare_env.sh"
        exit 1
    fi
}

# Function to start services
start_services() {
    echo "🚀 Starting all services..."
    
    # Check prerequisites
    check_prerequisites
    
    # Start Docker Compose if needed
    if [ -f "$DOCKER_COMPOSE_FILE" ]; then
        echo "🐳 Starting Docker Compose services..."
        docker compose up -d
    else
        echo "⚠️ No $DOCKER_COMPOSE_FILE found. Skipping Docker Compose startup."
    fi
    
    # Set up virtual environment
    if [ ! -d "$VENV_DIR" ]; then
        echo "📦 Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi
    
    source "$VENV_DIR/bin/activate"
    echo "📦 Installing Python dependencies..."
    pip install --upgrade pip
    pip install -r "$REQUIREMENTS_FILE"
    
    # Load environment variables if .env exists
    if [ -f .env ]; then
        echo "📄 Loading environment variables from .env..."
        export $(grep -v '^#' .env | xargs)
    fi
    
    # Run monitor script in background with logging
    echo "🚀 Starting service doctor with sudo..."
    
    # Create or clear log file
    > "$LOG_FILE"
    
    # Start the Python script with output redirected to log file only
    sudo "$VENV_DIR/bin/python" "$SCRIPT" >> "$LOG_FILE" 2>&1 &
    
    # Save PID for later cleanup
    echo $! > "$PID_FILE"
    echo "✅ Services started successfully. PID: $(cat $PID_FILE)"
    echo "📄 Logs are being written to: $LOG_FILE"
    echo "💡 To watch live logs, run: $0 watch"
}

# Function to stop services
stop_services() {
    echo "🛑 Stopping all services..."
    
    # Stop Python script if running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "🐍 Stopping Python script (PID: $PID)..."
            sudo kill $PID
            rm -f "$PID_FILE"
        else
            echo "⚠️ Python script not running or already stopped."
            rm -f "$PID_FILE"
        fi
    else
        echo "⚠️ No PID file found. Attempting to stop any running Python processes..."
        # Try to kill any running instances of the script
        sudo pkill -f "$SCRIPT" || echo "No Python processes found for $SCRIPT"
    fi
    
    # Deactivate virtual environment if active
    if [[ "$VIRTUAL_ENV" != "" ]]; then
        echo "📦 Deactivating virtual environment..."
        deactivate
    fi
    
    # Stop Docker Compose services
    if [ -f "$DOCKER_COMPOSE_FILE" ]; then
        echo "🐳 Stopping Docker Compose services..."
        docker compose stop
    else
        echo "⚠️ No $DOCKER_COMPOSE_FILE found. Skipping Docker Compose stop."
    fi
    
    echo "✅ All services stopped successfully."
}

# Function to clean up everything
clean_all() {
    echo "🧹 Cleaning up all resources..."
    
    # First stop everything
    stop_services
    
    # Remove Docker containers and images
    if [ -f "$DOCKER_COMPOSE_FILE" ]; then
        echo "🐳 Removing Docker containers and networks..."
        docker compose down --volumes --remove-orphans
        
        # Optional: Remove images (uncomment if you want to remove images too)
        # echo "🐳 Removing Docker images..."
        # docker compose down --volumes --remove-orphans --rmi all
    fi
    
    # Remove virtual environment
    if [ -d "$VENV_DIR" ]; then
        echo "📦 Removing Python virtual environment..."
        rm -rf "$VENV_DIR"
    fi
    
    # Remove PID file if exists
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi
    
    # Remove log file if exists
    if [ -f "$LOG_FILE" ]; then
        rm -f "$LOG_FILE"
    fi
    
    # Optional: Remove other generated files
    echo "🗑️ Removing temporary files..."
    rm -f *.log
    rm -f *.tmp
    
    echo "✅ Cleanup completed successfully."
}

# Function to watch logs
watch_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "❌ Log file not found: $LOG_FILE"
        echo "💡 Make sure the service is running first: $0 start"
        exit 1
    fi
    
    echo "👀 Watching live logs from: $LOG_FILE"
    echo "Press Ctrl+C to stop watching (service will continue running)"
    echo "===================================================================================="
    
    # Use tail -f to follow the log file
    tail -f "$LOG_FILE"
}

# Function to show recent logs
show_logs() {
    local lines=${2:-50}  # Default to 50 lines
    
    if [ ! -f "$LOG_FILE" ]; then
        echo "❌ Log file not found: $LOG_FILE"
        echo "💡 Make sure the service is running first: $0 start"
        exit 1
    fi
    
    echo "📄 Showing last $lines lines from: $LOG_FILE"
    echo "===================================================================================="
    tail -n "$lines" "$LOG_FILE"
}
show_status() {
    echo "📊 Service Status:"
    
    # Check Python script status
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "🐍 Python script: RUNNING (PID: $PID)"
        else
            echo "🐍 Python script: STOPPED (stale PID file)"
        fi
    else
        echo "🐍 Python script: STOPPED"
    fi
    
    # Check virtual environment
    if [ -d "$VENV_DIR" ]; then
        echo "📦 Virtual environment: EXISTS"
    else
        echo "📦 Virtual environment: NOT FOUND"
    fi
    
    # Check Docker services
    if [ -f "$DOCKER_COMPOSE_FILE" ]; then
        echo "🐳 Docker services:"
        docker compose ps
    else
        echo "🐳 Docker services: NO COMPOSE FILE"
    fi
}

# Function to show usage
show_usage() {
    echo "Usage: $0 {start|stop|clean|status|restart|watch|logs} [options]"
    echo ""
    echo "Commands:"
    echo "  start               - Start all services (Docker + Python)"
    echo "  stop                - Stop all services (keep containers and venv)"
    echo "  clean               - Stop and remove everything (containers, venv, etc.)"
    echo "  status              - Show current status of all services"
    echo "  restart             - Stop and start all services"
    echo "  watch               - Watch live logs from running Python app"
    echo "  logs [lines]        - Show recent logs (default: 50 lines)"
    echo ""
    echo "Examples:"
    echo "  $0 start            - Start services"
    echo "  $0 watch            - Watch live logs of running service"
    echo "  $0 logs 100         - Show last 100 log lines"
    echo "  $0 restart          - Restart services"
    echo ""
}

# Main logic
case "${1:-}" in
    start)
        start_services "$@"
        ;;
    stop)
        stop_services
        ;;
    clean)
        clean_all
        ;;
    status)
        show_status
        ;;
    restart)
        stop_services
        sleep 2
        start_services "$@"
        ;;
    watch)
        watch_logs
        ;;
    logs)
        show_logs "$@"
        ;;
    *)
        show_usage
        exit 1
        ;;
esac