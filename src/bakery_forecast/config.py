"""Experiment choices fixed before evaluating the final test period."""

SOURCE_URL = "https://www.kaggle.com/datasets/matthieugimbert/french-bakery-daily-sales"
DOWNLOAD_URL = "https://www.kaggle.com/api/v1/datasets/download/matthieugimbert/french-bakery-daily-sales"
EXPECTED_SHA256 = "af5eede55b6eb2efb6bebb0e6dd1a51568c7eb73554d2f8ad2563081025681b2"
RAW_NAME = "Bakery sales.csv"
SEED = 42

# Fixed scope: individually named, frequently sold baked goods, not slicing or bundles.
PRODUCTS = (
    "TRADITIONAL BAGUETTE", "CROISSANT", "PAIN AU CHOCOLAT", "BANETTE",
    "BAGUETTE", "CEREAL BAGUETTE", "BOULE 400G", "CAMPAGNE",
)
VALIDATION_FOLDS = (("2022-06-01", "2022-07-01"), ("2022-07-01", "2022-08-01"))
TEST_START = "2022-08-01"
TEST_END = "2022-10-01"  # exclusive
WARMUP_DAYS = 35
BASELINES = ("lag_7", "weekday_mean_4")
ML_MODELS = ("hgb_absolute", "hgb_poisson", "blend_absolute")
CANDIDATES = BASELINES + ML_MODELS
FEATURES = [
    "product", "dow", "month", "weekend", "annual_sin", "annual_cos", "trend",
    "lag_1", "lag_7", "lag_14", "lag_28", "mean_7", "mean_28", "std_28",
    "weekday_mean_4", "weekday_median_4", "observed_days_28",
]

# Scenarios are assumptions, not observed bakery accounting. Currency: EUR.
COST_RATIOS = (0.3, 0.5, 0.7)
SAFETY_MULTIPLIERS = (0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4)
