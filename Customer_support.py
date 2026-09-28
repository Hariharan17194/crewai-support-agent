import sys
from pathlib import Path

from support_core import DATA_DIR, answer_single, build_vector_db


def load_knowledge_base_file() -> Path:
    default_file = DATA_DIR / "amazon_customer_support.txt"

    path_str = input(
        f"Path to a .txt file of Amazon customer support content [default: {default_file}]: "
    ).strip()

    txt_path = Path(path_str) if path_str else default_file

    if not txt_path.exists():
        raise FileNotFoundError(f"'{txt_path}' does not exist.")
    if txt_path.suffix.lower() != ".txt":
        raise ValueError("Please provide a .txt file.")

    return txt_path


if __name__ == "__main__":
    chosen_path = Path(sys.argv[1]) if len(sys.argv) > 1 else load_knowledge_base_file()
    print(f"Indexing '{chosen_path.name}'...")
    vector_db = build_vector_db(chosen_path)

    query = input("\nCustomer Query: ")
    response = answer_single(query, vector_db)

    print("\nAgent Response:\n")
    print(response)
