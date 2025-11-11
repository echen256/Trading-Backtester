cd ./backend
mkdir -p logs
source venv/bin/activate

set -a  # Automatically export all variables
source ./.env
set +a

pytest tests