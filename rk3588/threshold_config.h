#ifndef THRESHOLD_CONFIG_H
#define THRESHOLD_CONFIG_H

/*
 * 阈值配置。
 *
 * 这些参数决定什么时候算异常。
 * 建议把它们放在 config.json 里，方便后续现场调整。
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
