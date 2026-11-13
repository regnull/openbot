# Hello World (C++)

A classic Hello World program that prints a greeting to stdout.

## Build and run

Requires a C++17 compiler (`g++` or `clang++`).

```bash
cd examples/hello_world
make run
```

Or without make:

```bash
g++ -std=c++17 -Wall -Wextra -Werror -O2 -o hello_world main.cpp
./hello_world
```
