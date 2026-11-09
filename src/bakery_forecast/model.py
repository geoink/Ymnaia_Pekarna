"""Small fixed model family. No random train/validation split or early stopping."""

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .config import SEED
from .features import baseline, model_input


def fit_models(training):
    models = {}
    for name, loss in (("hgb_absolute", "absolute_error"), ("hgb_poisson", "poisson")):
        estimator = HistGradientBoostingRegressor(
            loss=loss, learning_rate=0.06, max_iter=250, max_leaf_nodes=15,
            min_samples_leaf=20, l2_regularization=5.0, early_stopping=False,
            categorical_features=["product"], random_state=SEED,
        )
        with threadpool_limits(limits=1):
            estimator.fit(model_input(training), training.y)
        models[name] = estimator
    return models


def predict_candidates(frame, models):
    predictions = {name: baseline(frame, name) for name in ("lag_7", "weekday_mean_4")}
    for name, estimator in models.items():
        with threadpool_limits(limits=1):
            predictions[name] = np.maximum(0, estimator.predict(model_input(frame)))
    if "hgb_absolute" in predictions:
        predictions["blend_absolute"] = 0.5 * predictions["hgb_absolute"] + 0.5 * predictions["weekday_mean_4"]
    return predictions
