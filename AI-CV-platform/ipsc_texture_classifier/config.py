"""Shared configuration for the iPSC texture patch classifier.

Seven region classes are classified from texture + brightness features
(intensity histogram + Local Binary Pattern) with an SVM.
"""

# The seven region classes. Order defines the label index used everywhere
# (dataset folders, model classes, colour map).
CLASSES = [
    "single_cells",
    "medium_compaction",
    "full_compaction",
    "dead_cells",
    "differentiated_cells",
    "debris",
    "background",
]

# RGB colours used when painting a classified tile map.
CLASS_COLORS = {
    "single_cells": (220, 50, 40),
    "medium_compaction": (240, 210, 40),
    "full_compaction": (90, 190, 70),
    "dead_cells": (60, 110, 200),
    "differentiated_cells": (40, 180, 180),
    "debris": (120, 120, 120),
    "background": (210, 210, 210),
}

# --- Feature extraction -------------------------------------------------

# Number of bins in the normalized brightness histogram (over 0-255).
INTENSITY_BINS = 32

# Local Binary Pattern scales as (P neighbours, R radius). Each scale
# contributes P + 2 bins to the feature vector under the "uniform" method.
LBP_SCALES = [(8, 1), (16, 2)]
LBP_METHOD = "uniform"

# --- Tiling -------------------------------------------------------------

# Side length in px of a square patch fed to the classifier.
TILE_SIZE = 64

# Step between neighbouring tiles; equal to TILE_SIZE means no overlap.
TILE_STRIDE = 64
