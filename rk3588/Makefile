CC = gcc
CFLAGS = -std=c99 -Wall
LDFLAGS = -lpthread -lrt -lm
TARGET = inspection
SRCS = main.c thread_sensor.c thread_vision.c thread_decision.c thread_alarm.c thread_heartbeat.c threshold_config.c

all:
	$(CC) $(CFLAGS) -o $(TARGET) $(SRCS) $(LDFLAGS)

clean:
	rm -f $(TARGET)
