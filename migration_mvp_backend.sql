-- MVP backend migration (2026-03-04)

USE bst;

-- 1) 原始数据表索引优化（窗口查询关键索引）
ALTER TABLE device_monitoring_data
ADD INDEX idx_dev_ts (dev_num, device_timestamp);

-- 2) 检测流水表
CREATE TABLE IF NOT EXISTS detection_result_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    dev_num VARCHAR(50) NOT NULL,
    device_timestamp BIGINT NOT NULL,
    window_start_ts BIGINT NOT NULL,
    window_end_ts BIGINT NOT NULL,
    window_size INT NOT NULL,
    model_name VARCHAR(32) NOT NULL,
    model_version VARCHAR(64) NULL,
    is_anomaly TINYINT NOT NULL,
    anomaly_score DOUBLE NULL,
    threshold DOUBLE NULL,
    infer_latency_ms INT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ok',
    source VARCHAR(16) NOT NULL DEFAULT 'online',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_drl_dev_ts (dev_num, device_timestamp),
    INDEX idx_drl_created (created_at),
    INDEX idx_drl_request_id (request_id),
    INDEX idx_drl_source_ts (source, device_timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='检测结果流水表';

-- 3) 异常事件表（每小时一标注）
CREATE TABLE IF NOT EXISTS anomaly_event (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    dev_num VARCHAR(50) NOT NULL,
    event_hour_bucket BIGINT NOT NULL,
    first_detected_ts BIGINT NOT NULL,
    last_detected_ts BIGINT NOT NULL,
    display_mark_ts BIGINT NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'ongoing',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_dev_hour (dev_num, event_hour_bucket),
    INDEX idx_ae_dev_mark_ts (dev_num, display_mark_ts),
    INDEX idx_ae_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='异常事件表（按设备+小时去重）';

-- 4) 模型响应日志（分析专用，不影响主链路展示口径）
CREATE TABLE IF NOT EXISTS model_response_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id VARCHAR(64) NULL,
    dev_num VARCHAR(50) NOT NULL,
    device_timestamp BIGINT NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'online',
    requested_model_name VARCHAR(32) NOT NULL,
    effective_model_name VARCHAR(32) NOT NULL,
    model_version VARCHAR(64) NULL,
    is_anomaly TINYINT NOT NULL DEFAULT 0,
    anomaly_score DOUBLE NULL,
    threshold DOUBLE NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'unknown',
    risk_level VARCHAR(16) NULL,
    method VARCHAR(64) NULL,
    error_detail VARCHAR(500) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_mrl_dev_ts (dev_num, device_timestamp),
    INDEX idx_mrl_model_source_ts (requested_model_name, source, device_timestamp),
    INDEX idx_mrl_source_created (source, created_at),
    INDEX idx_mrl_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='模型响应日志（线上/回放/对比）';
