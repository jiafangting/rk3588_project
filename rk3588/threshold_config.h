#ifndef THRESHOLD_CONFIG_H
#define THRESHOLD_CONFIG_H

/*
 * 阈值配置结构体。
 *
 * 这些参数决定“什么时候算报警”。
 * 你可以把它理解成 RK3588 端的报警规则表。
 *
 * 字段说明：
 * - temp_max：环境温度上限
 * - humidity_min：环境湿度下限
 * - humidity_max：环境湿度上限
 * - current_max：工作电流上限
 * - temp_device_max：设备温度上限
 * - smoke_alarm：是否启用烟雾报警，1 表示启用，0 表示关闭
 *
 * 这些值通常来自 `config.json`，方便现场调参。
 */
typedef struct {
    float temp_max;
    float humidity_min;
    float humidity_max;
    float current_max;
    float temp_device_max;
    int   smoke_alarm;
} ThresholdConfig;

/*
 * 读取阈值配置。
 *
 * path: JSON 文件路径。
 * cfg : 输出配置结构体。
 *
 * 返回值：
 *   0  成功
 *  -1  失败（会自动回退默认值）
 */
int load_threshold(const char *path, ThresholdConfig *cfg);

#endif
