import os
import pickle
import traceback

path = 'ckd_model.pkl'
print('exists', os.path.exists(path))
if os.path.exists(path):
    try:
        with open(path, 'rb') as f:
            model = pickle.load(f)
        print('loaded', type(model))
    except Exception as e:
        print('error', type(e).__name__, e)
        traceback.print_exc()
