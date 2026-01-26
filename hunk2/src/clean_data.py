from pathlib import Path
import shutil

from .config import Config


def clean_data_area(cfg: Config) -> None:
    """
    Ensure DATA_AREA_ROOT_DIR exists and remove all files and folders inside it.

    This function is idempotent and safe to call multiple times. It will create the
    directory if it does not exist.
    """
    root = Path(cfg.data_area_root_dir)

    # create root if missing
    root.mkdir(parents=True, exist_ok=True)

    # iterate and remove children
    for child in root.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child)
                print(f"Removed directory: {child}")
            else:
                child.unlink()
                print(f"Removed file: {child}")
        except Exception as e:
            print(f"Varning: kunde inte ta bort {child}: {e}")