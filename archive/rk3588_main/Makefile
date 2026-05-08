CC ?= gcc
CFLAGS ?= -Wall -Wextra -O2 -g
TARGET = rk3588_main
OBJS = main.o vision_client.o decision_engine.o actuator_control.o

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS)

main.o: main.c vision_client.h decision_engine.h actuator_control.h
	$(CC) $(CFLAGS) -c main.c

vision_client.o: vision_client.c vision_client.h
	$(CC) $(CFLAGS) -c vision_client.c

decision_engine.o: decision_engine.c decision_engine.h vision_client.h
	$(CC) $(CFLAGS) -c decision_engine.c

actuator_control.o: actuator_control.c actuator_control.h decision_engine.h
	$(CC) $(CFLAGS) -c actuator_control.c

run: $(TARGET)
	./$(TARGET)

clean:
	rm -f $(TARGET) $(TARGET).exe $(OBJS)
