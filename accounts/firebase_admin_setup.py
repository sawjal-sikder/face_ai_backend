import firebase_admin #type: ignore
from firebase_admin import credentials #type: ignore

cred = credentials.Certificate("path/to/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
