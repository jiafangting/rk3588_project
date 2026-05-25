#include "threshold_config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*
 * 默认阈值。
 *
 * 这个函数的作用是：当 `config.json` 不存在、打不开、内容损坏时，
 * 给系统一个能继续运行的保底配置。
 *
 * 为什么要这样做：
 * - 工业软件不能因为配置文件坏了就直接崩掉；
 * - 先用默认阈值保证系统可运行，再慢慢排查配置问题。
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
    /*
     * 读取阈值配置。
     *
     * 参数：
     * - path：config.json 文件路径
     * - cfg：输出阈值结构体指针
     *
     * 返回值：
     * - 0：成功读取或至少完成默认值初始化
     * - -1：读取失败，cfg 中仍保留默认阈值
     *
     * 流程：
     * 1. 先写默认值；
     * 2. 打开 JSON 文件；
     * 3. 读入整个文件；
     * 4. 用字符串方式提取每个字段；
     * 5. 释放内存；
     * 6. 返回结果。
     */
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
