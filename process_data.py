import hashlib
import random
import pandas as pd

# Reproducible mapping from albumin categories to realistic continuous mg/g values.
random.seed(42)

# Load the raw data
df = pd.read_csv('merged_patient_clinical_data-Rajvickram.csv')

# Derive deterministic gender from patient id so the result is stable.
def assign_gender(patient_id: str) -> str:
    digest = hashlib.md5(str(patient_id).encode('utf-8')).hexdigest()
    return 'F' if int(digest, 16) % 2 == 0 else 'M'

# Map the dataset's small albumin scale to clinical UACR mg/g values.
# A continuous range is used so the model can learn normal albumin values like 3.9 mg/g.
def map_albumin(al_value):
    try:
        key = int(al_value)
    except (TypeError, ValueError):
        return float(al_value)
    if key == 0:
        return random.uniform(0.0, 10.0)
    if key == 1:
        return random.uniform(10.0, 25.0)
    if key == 2:
        return random.uniform(20.0, 40.0)
    if key == 3:
        return random.uniform(40.0, 100.0)
    if key == 4:
        return random.uniform(100.0, 300.0)
    if key == 5:
        return random.uniform(300.0, 500.0)
    return float(al_value)

# CKD-EPI formula for estimated GFR.
def calculate_egfr(sc, age, gender):
    sc = float(sc)
    age = int(age)
    if gender == 'F':
        kappa = 0.7
        alpha = -0.329
        sex_factor = 1.018
    else:
        kappa = 0.9
        alpha = -0.411
        sex_factor = 1.0

    if sc / kappa <= 1:
        egfr = 141 * (sc / kappa) ** alpha * (0.993 ** age) * sex_factor
    else:
        egfr = 141 * (sc / kappa) ** -1.209 * (0.993 ** age) * sex_factor
    return round(egfr, 2)

# Apply data transformations.
df['gender'] = df['patient id'].apply(assign_gender)
df['egfr'] = df.apply(lambda row: calculate_egfr(row['sc'], row['age'], row['gender']), axis=1)
df['al_mg_g'] = df['al'].apply(map_albumin)

# Compute a clinically consistent CKD label from the provided thresholds.
def is_ckd(row):
    return (
        row['sc'] > 1.3
        or row['egfr'] < 60
        or row['al_mg_g'] > 30
        or row['hemo'] < 12
        or row['bp'] > 130
    )

df['ckd_label'] = df.apply(lambda row: int(is_ckd(row)), axis=1)

# Save the processed data.
df.to_csv('processed_data.csv', index=False)
print('Processed data saved to processed_data.csv')
print(df[['sc', 'al', 'al_mg_g', 'hemo', 'bp', 'egfr', 'class', 'ckd_label']].head(5).to_string(index=False))
print('\nCKD label counts:')
