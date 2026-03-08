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
    status VARCHAR(16) NOT NULL DEFAULT 'ok',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_drl_dev_ts (dev_num, device_timestamp),
    INDEX idx_drl_created (created_at),
    INDEX idx_drl_request_id (request_id)
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
    status VARCHAR(16) NOT NULL DEFAULT 'ongoing',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_dev_hour (dev_num, event_hour_bucket),
    INDEX idx_ae_dev_mark_ts (dev_num, display_mark_ts),
    INDEX idx_ae_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='异常事件表（按设备+小时去重）';
