import json
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import zipfile


class StorageManager:
    def __init__(self, base_dir: str = "storage"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_json(self, data: List[Dict[str, Any]], filename: str = "pins.json") -> Path:
        filepath = self.base_dir / filename
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return filepath
        except Exception as e:
            print(f"Error saving JSON: {str(e)}")
            return None

    def load_json(self, filename: str) -> Optional[List[Dict[str, Any]]]:
        filepath = self.base_dir / filename
        
        if not filepath.exists():
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading JSON: {str(e)}")
            return None

    def save_xlsx(self, pins: List[Dict[str, Any]], filename: str = "pins.xlsx") -> Optional[Path]:
        try:
            from openpyxl import Workbook
            
            filepath = self.base_dir / filename
            wb = Workbook()
            ws = wb.active
            ws.title = "Pins"

            headers = ["ID", "Title", "Description", "URL", "Image URL", "Type", "Size", "Created"]
            ws.append(headers)

            for pin in pins:
                row = [
                    pin.get("id", ""),
                    pin.get("title", "")[:100],
                    pin.get("description", "")[:200],
                    pin.get("url", ""),
                    pin.get("image_url", ""),
                    pin.get("type", "image"),
                    "",
                    pin.get("created_at", ""),
                ]
                ws.append(row)

            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width

            wb.save(filepath)
            return filepath

        except ImportError:
            print("openpyxl not installed. Install with: pip install openpyxl")
            return None
        except Exception as e:
            print(f"Error saving XLSX: {str(e)}")
            return None

    def save_csv(self, pins: List[Dict[str, Any]], filename: str = "pins.csv") -> Optional[Path]:
        try:
            import csv
            
            filepath = self.base_dir / filename

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                fieldnames = ["id", "title", "description", "url", "image_url", "type", "created_at"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                writer.writeheader()
                for pin in pins:
                    writer.writerow({
                        field: pin.get(field, "") for field in fieldnames
                    })

            return filepath

        except Exception as e:
            print(f"Error saving CSV: {str(e)}")
            return None

    def create_zip(
        self,
        images_dir: str,
        output_file: str = "pins.zip",
        include_metadata: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        try:
            images_path = Path(images_dir)
            output_path = self.base_dir / output_file

            if not images_path.exists():
                print(f"Images directory not found: {images_dir}")
                return None

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for image_file in images_path.glob("*"):
                    if image_file.is_file():
                        zf.write(image_file, arcname=image_file.name)

                if include_metadata and metadata:
                    metadata_str = json.dumps(metadata, indent=2, ensure_ascii=False)
                    zf.writestr("metadata.json", metadata_str)

            return output_path

        except Exception as e:
            print(f"Error creating ZIP: {str(e)}")
            return None

    def cleanup_old_files(self, days: int = 7):
        import time
        
        now = time.time()
        cutoff = now - (days * 86400)

        try:
            for file in self.base_dir.glob("*"):
                if file.is_file() and file.stat().st_mtime < cutoff:
                    file.unlink()
                    print(f"Removed old file: {file.name}")
        except Exception as e:
            print(f"Error cleaning up files: {str(e)}")

    def get_statistics(self) -> Dict[str, Any]:
        total_size = 0
        file_count = 0

        try:
            for file in self.base_dir.glob("*"):
                if file.is_file():
                    total_size += file.stat().st_size
                    file_count += 1
        except Exception as e:
            print(f"Error getting statistics: {str(e)}")

        return {
            "total_files": file_count,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "storage_path": str(self.base_dir),
        }
