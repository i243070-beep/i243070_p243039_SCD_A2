# Indexing and retrieval pipeline

<!-- STARTER-TODO(3.1, 3.3, 5.2): fill each section with your numbers, then delete this comment. -->

## Extraction
Which documents needed OCR, one before-and-after example of a table, what could not be recovered.

## Cleaning
The rules you applied, and one thing you deliberately did not strip.

## Chunking
Size and overlap you shipped, storage amplification (stored tokens / original tokens),
and the three configurations you measured:

| Size (tokens) | Overlap (tokens) | recall@5 | Chunks stored |
| --- | --- | --- | --- |

## Embedding
Model, vector dimension, where the pin lives, how the API checks it.

## Semantic cache
Thresholds you tried, the false hit that ruled one out, the one you shipped.

## Evaluation method
How recall@k matches retrieved passages to golden ones (by source and section? by chunk id?).
