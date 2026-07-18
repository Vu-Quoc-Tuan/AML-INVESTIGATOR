import os
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, average_precision_score, precision_score, recall_score, f1_score

def main():
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_PATH = os.path.join(CURRENT_DIR, "training_data.csv")
    MODEL_PATH = os.path.join(CURRENT_DIR, "xgb_model.json")

    print(f"Loading training data from {DATA_PATH}...")
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Training data not found at {DATA_PATH}. Please run prepare_data.py first.")

    df = pd.read_csv(DATA_PATH)
    print(f"Loaded dataset with shape: {df.shape}")

    # Fill any NaNs with 0 (XGBoost handles NaNs but this is safer)
    df = df.fillna(0)

    # Set up X and y
    # Drop IDs and target
    X_cols = [c for c in df.columns if c not in ["transaction_id", "is_suspicious"]]
    X = df[X_cols]
    y = df["is_suspicious"]

    # Target class distribution
    pos_count = int(y.sum())
    neg_count = len(y) - pos_count
    pos_ratio = pos_count / len(y)
    print(f"Class distribution: Legitimate (0) = {neg_count}, Suspicious (1) = {pos_count} ({pos_ratio:.4%})")

    # Stratified Split (since all suspicious txns are at the end of the simulation timeline)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    print(f"Train size: {X_train.shape[0]}, Test size: {X_test.shape[0]}")
    print(f"Train suspicious ratio: {y_train.sum() / len(y_train):.4%}")
    print(f"Test suspicious ratio: {y_test.sum() / len(y_test):.4%}")

    # Calculate scale_pos_weight to handle severe imbalance safely
    pos_train_count = int(y_train.sum())
    neg_train_count = len(y_train) - pos_train_count
    scale_pos_weight = float(neg_train_count / pos_train_count) if pos_train_count > 0 else 1.0
    print(f"Calculated scale_pos_weight: {scale_pos_weight:.2f}")

    # Train XGBoost Classifier
    print("Training XGBoost model...")
    # Using default hyperparameters suitable for binary classification with imbalanced labels
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        eval_metric="logloss"
    )
    
    model.fit(X_train, y_train)
    print("Training complete!")

    # Evaluate the model
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    print("\n--- Model Evaluation (Test Set) ---")
    print(classification_report(y_test, y_pred, digits=4))

    pr_auc = average_precision_score(y_test, y_proba)
    print(f"Precision-Recall AUC (PR-AUC): {pr_auc:.4f}")

    # Calculate metrics manually for structured display
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    # Save model
    print(f"Saving model to {MODEL_PATH}...")
    model.save_model(MODEL_PATH)

    # Feature Importance
    print("\n--- Top 10 Most Important Features ---")
    importances = model.feature_importances_
    feat_importance = pd.DataFrame({
        "Feature": X_cols,
        "Importance": importances
    }).sort_values("Importance", ascending=False).reset_index(drop=True)

    print(feat_importance.head(10))

if __name__ == "__main__":
    main()
