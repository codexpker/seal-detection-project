CREATE TABLE IF NOT EXISTS device_monitoring_data (
    -- 主键
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- ========== 设备类型标识 ==========
    device_type TINYINT NOT NULL COMMENT '设备类型代码: 1=ABCTEMP, 2=MULTI_SENSOR',

    -- ========== 基础信息（来自JSON顶层）==========
    project_name VARCHAR(100) NOT NULL COMMENT '项目名称',
    project_num VARCHAR(100) COMMENT '项目编号',
    dev_name VARCHAR(100) NOT NULL COMMENT '设备名称',
    dev_num VARCHAR(50) NOT NULL COMMENT '设备编号',

    -- ========== 信号数据（来自datas对象）==========
    signal_snr FLOAT COMMENT '信噪比',
    signal_rsrp FLOAT COMMENT '参考信号接收功率',

    -- ========== 三相温度数据（统一字段）==========
    a_temp FLOAT COMMENT 'A相温度',
    b_temp FLOAT COMMENT 'B相温度',
    c_temp FLOAT COMMENT 'C相温度',

    -- ========== 室内环境数据（设备1&2统一）==========
    in_temp FLOAT COMMENT '室内温度',
    in_hum FLOAT COMMENT '室内湿度',

    -- ========== 室外环境数据（仅设备2）==========
    out_temp FLOAT COMMENT '室外温度',
    out_hum FLOAT COMMENT '室外湿度',

    -- ========== MLX传感器数据（仅设备2）==========
    mlx_max_temp FLOAT COMMENT 'MLX最大温度',
    mlx_min_temp FLOAT COMMENT 'MLX最小温度',
    mlx_avg_temp FLOAT COMMENT 'MLX平均温度',

    -- ========== 时间信息 ==========
    device_timestamp BIGINT NOT NULL COMMENT '设备时间戳（使用date字段/time字段）',

    -- ========== 原始数据备份 ==========
    raw_json JSON COMMENT '完整原始JSON',
    datas_json JSON COMMENT 'datas部分JSON',
    wavevalue_json JSON COMMENT 'Wavevalue部分JSON',

    -- ========== 系统字段 ==========
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- ========== 索引 ==========
    INDEX idx_device_type(device_type),
    INDEX idx_device_timestamp (device_timestamp),

    -- 防止重复数据
    UNIQUE KEY uk_device_time (dev_num, device_timestamp)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='设备监测表';

-- 1. 添加data_format字段
ALTER TABLE device_monitoring_data
ADD COLUMN data_format TINYINT DEFAULT 1 COMMENT '数据格式: 1=简单格式, 2=复杂格式';

-- 2. 更新device_type字段注释
ALTER TABLE device_monitoring_data
MODIFY COLUMN device_type TINYINT NOT NULL COMMENT '设备类型: 1=简单格式设备, 2=复杂格式设备';


