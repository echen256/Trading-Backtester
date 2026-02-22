REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$REPO_ROOT/backend"
mkdir -p logs
source venv/bin/activate

ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  set -a  # Automatically export all variables
  source "$ENV_FILE"
  set +a
elif [ -f ./.env ]; then
  set -a
  source ./.env
  set +a
fi

pytest tests
