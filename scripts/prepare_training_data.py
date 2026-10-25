"""Explicit user-attested local training-data preparation."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-attested-training-permission", action="store_true")
    parser.add_argument("--user-declared-game-export", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("PAMOS_ROOT", str(Path(__file__).resolve().parents[1]))
    from phiaimadeos.training_prepare import prepare_training
    result = prepare_training(user_training_permission=args.user_attested_training_permission,
        game_export_declared=args.user_declared_game_export,
        progress=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
    print(json.dumps({key: value for key, value in result.items() if key != "items"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
