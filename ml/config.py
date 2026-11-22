"""Shared configuration & constants for the TripWorld cross-city recommender spine."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data" / "tripworld"
DATA_SILVER_DIR = REPO_ROOT / "data" / "silver"
DATA_GOLD_DIR = REPO_ROOT / "data" / "gold"
PREDS_DIR = REPO_ROOT / "data" / "preds"
ARTIFACTS_DIR = REPO_ROOT / "backend" / "artifacts"
REPORTS_DIR = REPO_ROOT / "reports"
LEADERBOARD_PATH = REPORTS_DIR / "leaderboard.csv"

# Non-recommendable utility, transit, private residential, and generic city schemas
# identified during KDD Data Understanding (2.1M+ noisy check-ins).
NOISE_SCHEMAS: frozenset[str] = frozenset({
    "schema:TrainStation",
    "schema:SubwayStation",
    "schema:BusStation",
    "schema:Airport",
    "schema:TransitMap",
    "schema:ParkingFacility",
    "schema:GasStation",
    "schema:AutoDealer",
    "schema:AutoRepair",
    "schema:House",
    "schema:ApartmentComplex",
    "schema:Residence",
    "schema:Office",
    "schema:City",
    "schema:AdministrativeArea",
    "schema:Country",
    "schema:State",
    "schema:ConvenienceStore",
    "schema:PostOffice",
    "schema:BankOrCreditUnion",
    "schema:ATM",
    "schema:Hospital",
    "schema:MedicalClinic",
    "schema:Pharmacy",
    "schema:Dentist",
    "schema:GovernmentOffice",
    "schema:PoliceStation",
    "schema:FireStation",
    "schema:School",
    "schema:HighSchool",
    "schema:ElementarySchool",
    "schema:DryCleaningOrLaundry",
    "schema:MovingCompany",
})

# Cross-validation & benchmark defaults
N_FOLDS = 5
RANDOM_SEED = 42
MIN_HISTORY_POIS = 3
MIN_TARGET_POIS = 1
DEFAULT_TOP_K = 100
EVAL_KS = (5, 10, 20, 100)
