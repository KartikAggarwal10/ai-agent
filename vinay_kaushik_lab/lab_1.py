import json
import os
import warnings

import joblib
import matplotlib
import numpy as np
import pandas as pd

# Use non-interactive backend so plots save cleanly without blocking terminal execution
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.datasets import fetch_openml
from sklearn.feature_selection import RFE, SelectKBest, mutual_info_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

OUTPUT_DIR = "exp01_outputs"
PLOTS_DIR = os.path.join(OUTPUT_DIR, "plots")
DATASETS_DIR = os.path.join(OUTPUT_DIR, "datasets")
WEIGHTS_DIR = os.path.join(OUTPUT_DIR, "weights")

for directory in [OUTPUT_DIR, PLOTS_DIR, DATASETS_DIR, WEIGHTS_DIR]:
    os.makedirs(directory, exist_ok=True)


def print_section(title: str) -> None:
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}")


def main() -> None:
    # =========================================================================
    # PART A: LOAD AND INSPECT THE DATASET
    # =========================================================================
    print_section("PART A: LOAD AND INSPECT THE DATASET")
    adult = fetch_openml(name="adult", version=2, as_frame=True)
    df_raw = adult.frame.copy()  # Stage 1: Raw dataset (never overwritten)
    df = df_raw.copy()

    print("\n--- First 5 Rows ---")
    print(df.head().to_string())

    n_rows, n_cols = df.shape
    target_col = "class"
    feature_cols = [c for c in df.columns if c != target_col]

    # Separate numerical and categorical attributes (excluding target)
    num_cols = df[feature_cols].select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = df[feature_cols].select_dtypes(include=["category", "object", "bool"]).columns.tolist()

    print(f"\nNumber of observations (rows): {n_rows}")
    print(f"Number of total attributes (including target): {n_cols}")
    print(f"Target attribute: '{target_col}'")
    print(f"Numerical attributes ({len(num_cols)}): {num_cols}")
    print(f"Categorical attributes ({len(cat_cols)}): {cat_cols}")

    print("\n--- Data Types of All Attributes ---")
    print(df.dtypes.to_string())

    print("\n--- Basic Statistics for Numerical Attributes ---")
    print(df[num_cols].describe().T[["count", "mean", "std", "min", "25%", "50%", "75%", "max"]].to_string())

    dup_count = int(df.duplicated().sum())
    print(f"\nNumber of exact duplicate observations: {dup_count}")
    if dup_count > 0:
        df = df.drop_duplicates().reset_index(drop=True)
        print(f"Shape after removing exact duplicates: {df.shape}")

    # =========================================================================
    # PART B: EXPLORATORY DATA ANALYSIS
    # =========================================================================
    print_section("PART B: EXPLORATORY DATA ANALYSIS")

    target_counts = df[target_col].value_counts(dropna=False)
    target_pcts = df[target_col].value_counts(normalize=True, dropna=False) * 100
    target_summary = pd.DataFrame({"count": target_counts, "percentage": target_pcts.round(2)})
    print("\n--- Target Variable Distribution ---")
    print(target_summary.to_string())

    # Plot 1: Target distribution
    plt.figure(figsize=(7, 4.5))
    ax = sns.countplot(data=df, x=target_col, palette="Set2")
    plt.title("Distribution of Income Class (Target Variable)")
    plt.xlabel("Income Class")
    plt.ylabel("Number of Records")
    for container in ax.containers:
        ax.bar_label(container, fmt="%d", padding=3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "01_target_distribution.png"), dpi=150)
    plt.close()

    # Plot 2: Distributions of >= 4 numerical attributes
    selected_num_plots = [c for c in ["age", "hours-per-week", "capital-gain", "education-num"] if c in df.columns]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for ax_sub, col in zip(axes.flatten(), selected_num_plots):
        sns.histplot(df[col].dropna(), bins=30, kde=True, ax=ax_sub, color="steelblue")
        ax_sub.set_title(f"Distribution of {col}")
        ax_sub.set_xlabel(col)
        ax_sub.set_ylabel("Frequency")
    plt.suptitle("Numerical Attribute Distributions", fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "02_numerical_distributions.png"), dpi=150, bbox_inches="tight")
    plt.close()

    # Plot 3: Distributions of >= 3 categorical attributes
    selected_cat_plots = [c for c in ["workclass", "education", "marital-status", "occupation"] if c in df.columns][:3]
    fig, axes = plt.subplots(3, 1, figsize=(10, 12))
    for ax_sub, col in zip(axes, selected_cat_plots):
        order = df[col].astype(str).value_counts().index[:10]
        sns.countplot(data=df, y=col, order=order, ax=ax_sub, palette="viridis")
        ax_sub.set_title(f"Top Categories in {col}")
        ax_sub.set_xlabel("Number of Records")
        ax_sub.set_ylabel(col)
        top_cat = order[0]
        top_pct = (df[col].astype(str) == top_cat).mean() * 100
        print(f"Categorical '{col}' -> Most frequent: '{top_cat}' ({top_pct:.2f}%), Unique values: {df[col].nunique(dropna=False)}")
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "03_categorical_distributions.png"), dpi=150)
    plt.close()

    print(
        "\nClass Balance Observation: The target class is IMBALANCED (~76% '<=50K' vs ~24% '>50K'). "
        "Accuracy alone can be misleading (a naive majority-class model gets ~76% accuracy), so precision, "
        "recall, F1-score, ROC-AUC, and class weighting should be considered in classification experiments."
    )

    # =========================================================================
    # PART C: MISSING AND UNKNOWN VALUES
    # =========================================================================
    print_section("PART C: MISSING AND UNKNOWN VALUES")

    # Convert '?' (whether stored as str or category) into np.nan cleanly
    for col in df.columns:
        if isinstance(df[col].dtype, pd.CategoricalDtype):
            if "?" in df[col].cat.categories:
                df[col] = df[col].cat.remove_categories(["?"])
        elif df[col].dtype == object:
            df[col] = df[col].replace("?", np.nan)

    missing_counts = df.isnull().sum()
    missing_pcts = (df.isnull().mean() * 100).round(2)
    missing_table = pd.DataFrame({
        "attribute": df.columns,
        "missing_or_unknown_count": missing_counts.values,
        "pct_records_affected": missing_pcts.values,
    })
    print("\n--- Missing / Unknown Values Summary Table (All Attributes) ---")
    print(missing_table.to_string(index=False))

    affected_cols = missing_table[missing_table["missing_or_unknown_count"] > 0]["attribute"].tolist()
    print(f"\nAttributes with missing/unknown entries: {affected_cols}")

    # Compare 3 missing-value strategies on two categorical attributes ('workclass' and 'occupation')
    compare_cols = [c for c in ["workclass", "occupation"] if c in df.columns]
    for col in compare_cols:
        n_missing = int(df[col].isnull().sum())
        mode_val = df[col].mode(dropna=True)[0]
        n_drop = int(df[col].dropna().shape[0])
        n_mode = int(df[col].fillna(mode_val).shape[0])
        n_unk = int(df[col].astype(object).fillna("Unknown").shape[0])
        print(f"\nStrategy Comparison for '{col}' (missing={n_missing}, mode='{mode_val}'):")
        print(f"  1) Drop rows       -> retained rows: {n_drop} ({n_drop / len(df) * 100:.2f}%) | loses full records")
        print(f"  2) Mode imputation -> retained rows: {n_mode} (100.00%) | fills '{mode_val}', slightly inflating majority class")
        print(f"  3) 'Unknown' cat   -> retained rows: {n_unk} (100.00%) | preserves missingness signal (often informative in census data)")

    # Apply chosen strategy:
    # - Drop rows if target or critical numeric features are missing
    # - For categorical attributes with missing values, add 'Unknown' category (retains rows & missingness information)
    df_cleaned = df.dropna(subset=[target_col] + num_cols).copy()
    for col in cat_cols:
        if isinstance(df_cleaned[col].dtype, pd.CategoricalDtype):
            if "Unknown" not in df_cleaned[col].cat.categories:
                df_cleaned[col] = df_cleaned[col].cat.add_categories(["Unknown"])
            df_cleaned[col] = df_cleaned[col].fillna("Unknown")
        else:
            df_cleaned[col] = df_cleaned[col].fillna("Unknown")

    print(f"\nCleaned dataset shape: {df_cleaned.shape} | Remaining NaNs: {int(df_cleaned.isnull().sum().sum())}")
    print(
        "Justification: Using 'Unknown' for missing categorical entries preserves all records and allows models "
        "to learn if unreported workclass/occupation correlates with income rather than distorting counts with the mode."
    )

    # =========================================================================
    # PART D: FEATURE ENGINEERING
    # =========================================================================
    print_section("PART D: FEATURE ENGINEERING")

    df_fe = df_cleaned.copy()

    # 1. age_group
    df_fe["age_group"] = pd.cut(
        df_fe["age"],
        bins=[0, 25, 40, 60, 100],
        labels=["Young", "Adult", "Middle-aged", "Senior"],
        include_lowest=True,
    )

    # 2. work_hours_group
    df_fe["work_hours_group"] = pd.cut(
        df_fe["hours-per-week"],
        bins=[-1, 34, 40, 60, 120],
        labels=["Part-time", "Standard", "Overtime", "Extreme"],
    )

    # 3. net_capital
    df_fe["net_capital"] = df_fe["capital-gain"] - df_fe["capital-loss"]

    # 4. education_group (from education-num if available)
    if "education-num" in df_fe.columns:
        df_fe["education_group"] = pd.cut(
            df_fe["education-num"],
            bins=[0, 8, 12, 14, 20],
            labels=["Basic", "HighSchool_SomeCollege", "Bachelors_Plus", "Advanced_Degree"],
        )

    engineered_cols = [c for c in ["age_group", "work_hours_group", "net_capital", "education_group"] if c in df_fe.columns]
    print(f"Created {len(engineered_cols)} new features: {engineered_cols}")
    print("\n--- Sample of Engineered Features ---")
    print(df_fe[[c for c in ["age", "age_group", "hours-per-week", "work_hours_group", "capital-gain", "capital-loss", "net_capital"] if c in df_fe.columns]].head(8).to_string())

    print("\n--- Feature Justifications ---")
    print("* age_group: Captures non-linear career progression stages that linear age may under-represent.")
    print("* work_hours_group: Separates part-time, standard full-time, overtime, and extreme work schedules tied to earning potential.")
    print("* net_capital: Combines capital gains and capital losses into a single net investment signal, reducing redundancy.")
    if "education_group" in engineered_cols:
        print("* education_group: Groups credential levels into meaningful attainment tiers that often govern salary brackets.")

    # =========================================================================
    # PART E: ENCODING AND SCALING
    # =========================================================================
    print_section("PART E: ENCODING AND SCALING")

    # Binary encode target: '>50K' (or '>50K.') -> 1, else -> 0
    y_binary = df_fe[target_col].astype(str).str.contains(">50K", regex=False).astype(int)
    X_before_enc = df_fe.drop(columns=[target_col]).copy()

    cat_to_encode = X_before_enc.select_dtypes(include=["category", "object", "bool"]).columns.tolist()
    df_encoded_features = pd.get_dummies(X_before_enc, columns=cat_to_encode, drop_first=True, dtype=float)
    df_encoded = df_encoded_features.copy()
    df_encoded["target_income_gt50k"] = y_binary.values

    print(f"Shape before one-hot encoding (without target): {X_before_enc.shape}")
    print(f"Shape after one-hot encoding  (without target): {df_encoded_features.shape}")

    # Standardization on numerical columns (before scaling vs after scaling)
    num_to_scale = [
        c for c in ["age", "fnlwgt", "education-num", "capital-gain", "capital-loss", "hours-per-week", "net_capital"]
        if c in df_encoded_features.columns
    ]

    before_stats = df_encoded_features[num_to_scale].agg(["mean", "std"]).T
    before_stats.columns = ["mean_before", "std_before"]

    scaler = StandardScaler()
    scaled_num_array = scaler.fit_transform(df_encoded_features[num_to_scale])

    df_scaled = df_encoded_features.copy()
    df_scaled[num_to_scale] = scaled_num_array

    after_stats = pd.DataFrame({
        "mean_after": df_scaled[num_to_scale].mean(),
        "std_after": df_scaled[num_to_scale].std(ddof=0),
    })

    scaling_comparison = pd.concat([before_stats, after_stats], axis=1).round(4)
    print("\n--- Standardization Comparison (Before vs After StandardScaler) ---")
    print(scaling_comparison.to_string())

    df_encoded_scaled = df_scaled.copy()
    df_encoded_scaled["target_income_gt50k"] = y_binary.values

    print(
        "\nWhy Scaling Matters for KNN & SVM: KNN relies on Euclidean/distance metrics and SVM uses margins/kernels "
        "(such as RBF). Unscaled large-magnitude features (e.g., capital-gain or fnlwgt up to tens/hundreds of thousands) "
        "dominate distance and inner-product calculations over smaller-scale features."
    )

    # =========================================================================
    # PART F: OUTLIER ANALYSIS
    # =========================================================================
    print_section("PART F: OUTLIER ANALYSIS")

    boxplot_cols = [c for c in ["age", "hours-per-week", "capital-gain"] if c in df_fe.columns]
    fig, axes = plt.subplots(1, len(boxplot_cols), figsize=(15, 4.5))
    for ax_sub, col in zip(axes, boxplot_cols):
        sns.boxplot(x=df_fe[col], ax=ax_sub, color="coral")
        ax_sub.set_title(f"Box Plot: {col}")
        ax_sub.set_xlabel(col)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "04_outlier_boxplots.png"), dpi=150)
    plt.close()

    # IQR outlier check on 'hours-per-week'
    q1 = df_fe["hours-per-week"].quantile(0.25)
    q3 = df_fe["hours-per-week"].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    iqr_outliers = df_fe[(df_fe["hours-per-week"] < lower_bound) | (df_fe["hours-per-week"] > upper_bound)]
    print(f"\nIQR Analysis on 'hours-per-week':")
    print(f"  Q1={q1:.2f}, Q3={q3:.2f}, IQR={iqr:.2f}")
    print(f"  Lower bound={lower_bound:.2f}, Upper bound={upper_bound:.2f}")
    print(f"  Potential outliers detected: {len(iqr_outliers)} ({len(iqr_outliers) / len(df_fe) * 100:.2f}%)")

    sample_cols = [c for c in ["age", "workclass", "occupation", "hours-per-week", "class"] if c in iqr_outliers.columns]
    print("\n--- Sample Detected 'hours-per-week' Outliers ---")
    print(iqr_outliers[sample_cols].head(8).to_string())

    print(
        "\nOutlier Decision: Retain observations for now (do not blindly drop). Values like 50–99 hours/week or "
        "high capital-gain represent genuine real-world working patterns or high-income individuals rather than data-entry errors."
    )

    # =========================================================================
    # PART G: FEATURE SELECTION
    # =========================================================================
    print_section("PART G: FEATURE SELECTION")

    num_corr_cols = df_fe.select_dtypes(include=[np.number]).columns.tolist()
    corr_matrix = df_fe[num_corr_cols].corr()

    plt.figure(figsize=(10, 7))
    sns.heatmap(corr_matrix, annot=True, fmt=".2f", cmap="coolwarm", center=0)
    plt.title("Correlation Matrix of Numerical Attributes")
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "05_correlation_matrix.png"), dpi=150)
    plt.close()

    # Identify highly correlated numerical pairs (|r| >= 0.7, excluding self)
    high_corr_pairs = []
    for i in range(len(num_corr_cols)):
        for j in range(i + 1, len(num_corr_cols)):
            r_val = corr_matrix.iloc[i, j]
            if abs(r_val) >= 0.70:
                high_corr_pairs.append((num_corr_cols[i], num_corr_cols[j], round(float(r_val), 4)))

    print("\n--- Highly Correlated Numerical Pairs (|r| >= 0.70) ---")
    if high_corr_pairs:
        for a, b, r_val in high_corr_pairs:
            print(f"  {a}  <-->  {b} : r = {r_val}")
    else:
        print("  No numerical pairs with |r| >= 0.70 found.")

    X = df_scaled.copy()
    y = y_binary.copy()

    k_features = min(15, X.shape[1])
    mi_selector = SelectKBest(score_func=mutual_info_classif, k=k_features)
    mi_selector.fit(X, y)
    mi_scores = pd.Series(mi_selector.scores_, index=X.columns).sort_values(ascending=False)
    mi_selected = X.columns[mi_selector.get_support()].tolist()

    print(f"\n--- Top {k_features} Features by Mutual Information ---")
    print(mi_scores.head(k_features).round(4).to_string())

    # Recursive Feature Elimination (RFE) with Logistic Regression
    base_clf = LogisticRegression(max_iter=1000, random_state=42)
    rfe_selector = RFE(estimator=base_clf, n_features_to_select=k_features, step=max(1, X.shape[1] // 20))
    rfe_selector.fit(X, y)
    rfe_selected = X.columns[rfe_selector.get_support()].tolist()

    overlap = sorted(set(mi_selected).intersection(set(rfe_selected)))
    print(f"\n--- Top {k_features} Features Selected by RFE (Logistic Regression) ---")
    print(rfe_selected)
    print(f"\nOverlap between Mutual Information and RFE ({len(overlap)}/{k_features} features): {overlap}")

    # Combine top features (prioritizing RFE + top MI so model has rich signal)
    final_selected_cols = list(dict.fromkeys(rfe_selected + mi_selected[:5]))

    # =========================================================================
    # SECTION 7: SAVE ALL 5 STAGES + MODEL WEIGHTS & ARTIFACTS
    # =========================================================================
    print_section("SECTION 7 & WEIGHTS: SAVING DATASETS AND MODEL WEIGHTS")

    df_selected = df_scaled[final_selected_cols].copy()
    df_selected["target_income_gt50k"] = y.values

    # Save 5 required stages without modifying raw data
    stage_paths = {
        "01_raw_dataset.csv": df_raw,
        "02_cleaned_dataset.csv": df_cleaned,
        "03_feature_engineered_dataset.csv": df_fe,
        "04_encoded_scaled_dataset.csv": df_encoded_scaled,
        "05_selected_features_dataset.csv": df_selected,
    }
    for fname, stage_df in stage_paths.items():
        fpath = os.path.join(DATASETS_DIR, fname)
        stage_df.to_csv(fpath, index=False)
        print(f"Saved stage -> {fpath}  (shape={stage_df.shape})")

    # Train final LogisticRegression classifier on selected features and save weights
    X_sel = df_scaled[final_selected_cols]
    X_train, X_test, y_train, y_test = train_test_split(
        X_sel, y, test_size=0.2, random_state=42, stratify=y
    )

    final_model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
    final_model.fit(X_train, y_train)

    y_pred = final_model.predict(X_test)
    y_prob = final_model.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_prob)

    print(f"\nBaseline LogisticRegression on Selected Features -> Accuracy: {acc:.4f} | ROC-AUC: {auc:.4f}")
    print("\n--- Classification Report (Test Set) ---")
    print(classification_report(y_test, y_pred, target_names=["<=50K", ">50K"], digits=4))

    # Save weights in .npz, joblib pipeline bundle, and readable JSON summary
    weights_npz_path = os.path.join(WEIGHTS_DIR, "logistic_regression_weights.npz")
    np.savez(
        weights_npz_path,
        coef=final_model.coef_,
        intercept=final_model.intercept_,
        scaler_mean=scaler.mean_,
        scaler_scale=scaler.scale_,
    )

    bundle_path = os.path.join(WEIGHTS_DIR, "preprocessing_and_model_bundle.joblib")
    joblib.dump(
        {
            "scaler": scaler,
            "scaled_numeric_columns": num_to_scale,
            "encoded_feature_columns": df_encoded_features.columns.tolist(),
            "selected_features": final_selected_cols,
            "model": final_model,
        },
        bundle_path,
    )

    feature_weights = {
        feat: float(w)
        for feat, w in sorted(
            zip(final_selected_cols, final_model.coef_[0]),
            key=lambda item: abs(item[1]),
            reverse=True,
        )
    }
    weights_json_path = os.path.join(WEIGHTS_DIR, "model_weights_summary.json")
    with open(weights_json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "intercept": float(final_model.intercept_[0]),
                "test_accuracy": round(float(acc), 4),
                "test_roc_auc": round(float(auc), 4),
                "feature_weights": feature_weights,
            },
            f,
            indent=2,
        )

    print(f"Saved NumPy weights -> {weights_npz_path}")
    print(f"Saved Joblib bundle -> {bundle_path}")
    print(f"Saved JSON weights  -> {weights_json_path}")
    print(f"Saved plots in      -> {PLOTS_DIR}")


if __name__ == "__main__":
    main()