import json
from pathlib import Path
from typing import Set, Optional
from datetime import datetime


class DedupeStore:
    def __init__(self, storage_file: str = ".seen_pins.json"):
        self.storage_file = Path(storage_file)
        self.seen_ids: Set[str] = set()
        self.load()

    def load(self):
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r") as f:
                    data = json.load(f)
                    self.seen_ids = set(data.get("ids", []))
            except Exception as e:
                print(f"Error loading dedup store: {str(e)}")
                self.seen_ids = set()

    def save(self):
        try:
            with open(self.storage_file, "w") as f:
                json.dump(
                    {
                        "ids": list(self.seen_ids),
                        "count": len(self.seen_ids),
                        "updated_at": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            print(f"Error saving dedup store: {str(e)}")

    def has(self, pin_id: str) -> bool:
        return pin_id in self.seen_ids

    def add(self, pin_id: str):
        self.seen_ids.add(pin_id)

    def add_many(self, pin_ids: list):
        self.seen_ids.update(pin_ids)

    def remove(self, pin_id: str):
        self.seen_ids.discard(pin_id)

    def clear(self):
        self.seen_ids.clear()
        self.save()

    def count(self) -> int:
        return len(self.seen_ids)

    def deduplicate_pins(self, pins: list) -> tuple[list, int]:
        unique_pins = []
        skipped = 0

        for pin in pins:
            pin_id = pin.get("id") or pin.get("url")
            
            if not pin_id:
                unique_pins.append(pin)
                continue

            if self.has(pin_id):
                skipped += 1
            else:
                unique_pins.append(pin)
                self.add(pin_id)

        self.save()
        return unique_pins, skipped
