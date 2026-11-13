CXX ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Werror -O2

.PHONY: all run test clean

all: hello_world

hello_world: main.cpp
	$(CXX) $(CXXFLAGS) -o $@ main.cpp

run: hello_world
	./hello_world

test: run

clean:
	rm -f hello_world
