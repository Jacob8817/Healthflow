"""Safety audit for the untrained NHS England forecasting notebook."""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path

MANUAL_TAGS={"manual_training","manual_tuning","manual_evaluation","manual_export"}
FLAGS={"ALLOW_MODEL_TRAINING","ALLOW_MODEL_TUNING","ALLOW_FINAL_EVALUATION","ALLOW_MODEL_EXPORT"}
BANNED_LEGACY=("mimic","physionet","edstays","patients.csv.gz","hadm_id",
               "physionet_username","physionet_password")


def root(): return Path(__file__).resolve().parents[2]

def source_text(cell):
    source=cell.get("source","")
    return "".join(source) if isinstance(source,list) else source


def assigned_flags(source):
    values={}
    tree=ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in FLAGS:
                    values[target.id]=node.value.value
    return values


def audit(path):
    errors=[]
    notebook=json.loads(path.read_text(encoding="utf-8"))
    all_source="\n".join(source_text(cell) for cell in notebook["cells"]).lower()
    values={}
    for cell in notebook["cells"]:
        if cell["cell_type"]=="code":
            try: values.update(assigned_flags(source_text(cell)))
            except SyntaxError as exc: errors.append(f"Syntax error: {exc}")
    for flag in FLAGS:
        if values.get(flag) is not False: errors.append(f"{flag} must be False.")
    for token in BANNED_LEGACY:
        if token in all_source: errors.append(f"Legacy token remains in notebook: {token}")
    for index,cell in enumerate(notebook["cells"]):
        tags=set(cell.get("metadata",{}).get("tags",[]))
        if tags & MANUAL_TAGS:
            if cell.get("execution_count") is not None: errors.append(f"Manual cell {index} executed.")
            if cell.get("outputs"): errors.append(f"Manual cell {index} has outputs.")
            if not source_text(cell).lstrip().startswith("assert ALLOW_"):
                errors.append(f"Manual cell {index} lacks leading permission assertion.")
    artifacts=root()/"backend/model_artifacts/emergency_admissions_forecast"
    for file in artifacts.rglob("*"):
        if file.is_file() and file.suffix.lower() in {".joblib",".pkl",".onnx",".json",".csv",".md"}:
            errors.append(f"Generated model artifact exists: {file}")
    for file in (root()/"backend/reports/emergency_admissions_forecast/metrics").glob("*"):
        if file.is_file() and file.name!=".gitkeep":
            errors.append(f"Final metric file exists: {file}")
    return errors


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("notebook",nargs="?",type=Path,
      default=root()/"backend/notebooks/healthflow_main_model_training.ipynb")
    errors=audit(parser.parse_args().notebook.resolve())
    if errors:
        print("Safety audit FAILED:\n"+"\n".join(f"- {item}" for item in errors));return 1
    print("Safety audit passed: all flags false, manual cells clean, no legacy workflow or artifacts.")
    return 0


if __name__=="__main__": raise SystemExit(main())
