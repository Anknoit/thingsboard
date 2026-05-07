"""
Predictive maintenance batch job — stub.
Full implementation in Phase 6.
"""

import logging

logger = logging.getLogger(__name__)


async def run_predictive_batch() -> None:
    """
    Scores all BMS devices with the LSTM model and creates predictive alarms.
    Phase 6 replaces this stub with the full implementation.
    """
    logger.info("predictive_batch: starting (stub — full impl in Phase 6)")
    # Phase 6 implementation will:
    # 1. Query TBClient for all BMS devices
    # 2. Call LSTMPredictiveService.score_device() for each
    # 3. Write health scores to TimescaleDB
    # 4. Create PREDICTIVE_FAILURE alarms for devices above threshold
    # 5. Create work orders in PostgreSQL
    logger.info("predictive_batch: complete (stub)")
