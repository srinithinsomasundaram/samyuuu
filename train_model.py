import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score, classification_report
import pickle

# Load processed data
df = pd.read_csv('processed_data.csv')

# Use a clinically consistent albumin value and derived CKD label.
features = ['sc', 'al_mg_g', 'hemo', 'bp', 'egfr']
X = df[features]

df['ckd_label'] = df['ckd_label'].astype(int)
y = df['ckd_label']

# Split the data
random_state = 42
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=random_state)

# Train model
model = DecisionTreeClassifier(random_state=random_state)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
print(f'Accuracy: {accuracy_score(y_test, y_pred):.4f}')
print(classification_report(y_test, y_pred, target_names=['notckd', 'ckd']))

# Save model
with open('ckd_model.pkl', 'wb') as f:
    pickle.dump(model, f)

print('Model saved to ckd_model.pkl')
