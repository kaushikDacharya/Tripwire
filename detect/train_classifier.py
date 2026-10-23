"""
Train the injection classifier.

Usage:
    python -m detect.train_classifier

Attempts to load deepset/prompt-injections from Hugging Face.
Falls back to built-in training data if unavailable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detect.injection import train_classifier


def main():
    print("Training injection classifier...")
    print("(Attempting Hugging Face dataset, falling back to built-in data)")
    print()

    try:
        results = train_classifier()
        print("Training complete!")
        print(f"  Precision: {results['precision']:.4f}")
        print(f"  Recall:    {results['recall']:.4f}")
        print(f"  F1:        {results['f1']:.4f}")
        print(f"  Accuracy:  {results['accuracy']:.4f}")
        print(f"  Train:     {results['train_size']} samples")
        print(f"  Test:      {results['test_size']} samples")
        print()
        print(f"Model saved to detect/classifier_model/")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
