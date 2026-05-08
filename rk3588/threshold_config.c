#include "threshold_config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*
 * 默认阈值。
 *
 * 这些值是文件不存在或解析失败时的保底值，
 * 保证系统没有 config.json 也能先跑起来。
 */
static void set_default_threshold(ThresholdConfig *cfg)
{
    if (!cfg) {
        return;
    }

    cfg->temp_max = 60.0f;
    cfg->humidity_min = 20.0f;
    cfg->humidity_max = 80.0f;
    cfg->current_max = 10.0f;
    cfg->temp_device_max = 80.0f;
    cfg->smoke_alarm = 1;
}

/*
 * 从 JSON 文本里手工提取浮点数。
 *
 * 说明：这里不依赖第三方 JSON 库，
 * 只做最基础的字符串查找 + sscanf。
 */
static int parse_float_field(const char *text, const char *key, float *out)
{
    const char *pos = strstr(text, key);
    if (!pos || !out) {
        return -1;
    }

    pos = strchr(pos, ':');
    if (!pos) {
        return -1;
    }

    if (sscanf(pos + 1, "%f", out) != 1) {
        return -1;
    }
    return 0;
}

/*
 * 从 JSON 文本里手工提取整数。
 */
static int parse_int_field(const char *text, const char *key, int *out)
{
    const char *pos = strstr(text, key);
    if (!pos || !out) {
        return -1;
    }

    pos = strchr(pos, ':');
    if (!pos) {
        return -1;
    }

    if (sscanf(pos + 1, "%d", out) != 1) {
        return -1;
    }
    return 0;
}

int load_threshold(const char *path, ThresholdConfig *cfg)
{
    FILE *fp = NULL;
    long file_size = 0;
    char *buf = NULL;
    size_t read_size = 0;

    if (!cfg) {
        return -1;
    }

    /* 先写默认值，避免任何失败导致阈值未初始化。 */
    set_default_threshold(cfg);

    if (!path) {
        printf("[CONFIG] 未提供 config.json 路径，使用默认阈值\n");
        return -1;
    }

    fp = fopen(path, "r");
    if (!fp) {
        printf("[CONFIG] 无法打开 %s，使用默认阈值\n", path);
        return -1;
    }

    if (fseek(fp, 0, SEEK_END) != 0) {
        printf("[CONFIG] 读取 config.json 失败，使用默认阈值\n");
        fclose(fp);
        return -1;
    }

    file_size = ftell(fp);
    if (file_size <= 0) {
        printf("[CONFIG] config.json 为空，使用默认阈值\n");
        fclose(fp);
        return -1;
    }

    if (fseek(fp, 0, SEEK_SET) != 0) {
        printf("[CONFIG] 回到文件开头失败，使用默认阈值\n");
        fclose(fp);
        return -1;
    }

    buf = (char *)malloc((size_t)file_size + 1);
    if (!buf) {
        printf("[CONFIG] 内存不足，使用默认阈值\n");
        fclose(fp);
        return -1;
    }

    read_size = fread(buf, 1, (size_t)file_size, fp);
    buf[read_size] = '\0';
    fclose(fp);

    /* 逐项解析，解析失败就保留默认值。 */
    parse_float_field(buf, "temp_max", &cfg->temp_max);
    parse_float_field(buf, "humidity_min", &cfg->humidity_min);
    parse_float_field(buf, "humidity_max", &cfg->humidity_max);
    parse_float_field(buf, "current_max", &cfg->current_max);
    parse_float_field(buf, "temp_device_max", &cfg->temp_device_max);
    parse_int_field(buf, "smoke_alarm", &cfg->smoke_alarm);

    free(buf);
    printf("[CONFIG] 阈值配置加载完成\n");
    return 0;
}
