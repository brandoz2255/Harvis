# Hello World Test Commands for VibeCode Production

## Overview
This document provides ready-to-use "Hello World" examples for testing all supported file types in VibeCode IDE. Each example is production-ready and demonstrates the core capabilities of each language.

## JavaScript & Node.js

### `hello.js`
```javascript
console.log("Hello, World!");
console.log("Node.js version:", process.version);
console.log("Platform:", process.platform);
```

### `hello.mjs` (ES Modules)
```javascript
console.log("Hello, World from ES Module!");
console.log("Current time:", new Date().toISOString());
```

### `hello.ts` (TypeScript)
```typescript
interface Greeting {
  message: string;
  timestamp: Date;
}

const greeting: Greeting = {
  message: "Hello, World from TypeScript!",
  timestamp: new Date()
};

console.log(greeting.message);
console.log("Timestamp:", greeting.timestamp.toISOString());
```

## Python

### `hello.py`
```python
print("Hello, World!")
print("Python version:", __import__('sys').version)
print("Current time:", __import__('datetime').datetime.now())
```

### `hello_advanced.py`
```python
import sys
import datetime
import json

def greet(name="World"):
    return f"Hello, {name}!"

def main():
    data = {
        "message": greet(),
        "python_version": sys.version,
        "timestamp": datetime.datetime.now().isoformat(),
        "platform": sys.platform
    }
    
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    main()
```

## Bash/Shell Scripts

### `hello.sh`
```bash
#!/bin/bash
echo "Hello, World!"
echo "Shell: $SHELL"
echo "User: $USER"
echo "Date: $(date)"
```

### `hello_advanced.sh`
```bash
#!/bin/bash
echo "Hello, World from Bash!"
echo "Script name: $0"
echo "Arguments: $@"
echo "Process ID: $$"
echo "Current directory: $(pwd)"
```

## Ruby

### `hello.rb`
```ruby
puts "Hello, World!"
puts "Ruby version: #{RUBY_VERSION}"
puts "Current time: #{Time.now}"
```

### `hello_advanced.rb`
```ruby
class Greeter
  def initialize(name = "World")
    @name = name
  end
  
  def greet
    "Hello, #{@name}!"
  end
  
  def info
    {
      message: greet,
      ruby_version: RUBY_VERSION,
      timestamp: Time.now.iso8601,
      platform: RUBY_PLATFORM
    }
  end
end

greeter = Greeter.new
puts greeter.info
```

## Go

### `hello.go`
```go
package main

import (
    "fmt"
    "runtime"
    "time"
)

func main() {
    fmt.Println("Hello, World!")
    fmt.Printf("Go version: %s\n", runtime.Version())
    fmt.Printf("OS: %s\n", runtime.GOOS)
    fmt.Printf("Arch: %s\n", runtime.GOARCH)
    fmt.Printf("Time: %s\n", time.Now().Format(time.RFC3339))
}
```

## Java

### `Hello.java`
```java
public class Hello {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
        System.out.println("Java version: " + System.getProperty("java.version"));
        System.out.println("OS: " + System.getProperty("os.name"));
        System.out.println("Time: " + java.time.LocalDateTime.now());
    }
}
```

## C

### `hello.c`
```c
#include <stdio.h>
#include <time.h>

int main() {
    printf("Hello, World!\n");
    printf("C compiler working!\n");
    
    time_t now = time(NULL);
    printf("Current time: %s", ctime(&now));
    
    return 0;
}
```

## C++

### `hello.cpp`
```cpp
#include <iostream>
#include <chrono>
#include <ctime>

int main() {
    std::cout << "Hello, World!" << std::endl;
    std::cout << "C++ compiler working!" << std::endl;
    
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    std::cout << "Current time: " << std::ctime(&time_t);
    
    return 0;
}
```

## Data Files (Non-Executable)

### `hello.json`
```json
{
  "message": "Hello, World!",
  "language": "JSON",
  "timestamp": "2024-01-01T00:00:00Z",
  "features": [
    "Data storage",
    "API responses",
    "Configuration"
  ]
}
```

### `hello.yaml`
```yaml
message: "Hello, World!"
language: "YAML"
timestamp: "2024-01-01T00:00:00Z"
features:
  - "Configuration"
  - "Data serialization"
  - "Human readable"
```

### `hello.md`
```markdown
# Hello, World!

This is a **Markdown** file demonstrating:

- Text formatting
- Lists
- Code blocks
- Links

## Features

1. Documentation
2. README files
3. Rich text formatting

```javascript
console.log("Code in markdown!");
```
```

## Testing Instructions

### 1. Create Files
1. Create each file in the IDE using the "+" button in the file explorer
2. Copy the content for each language
3. Save the files

### 2. Test Execution
1. Click the "Run" button next to each file
2. Verify the output appears in the output tab
3. Check that the correct runtime is used

### 3. Expected Results

| File Type | Runtime | Expected Output |
|-----------|---------|-----------------|
| `hello.js` | Node.js | "Hello, World!" + Node version |
| `hello.py` | Python | "Hello, World!" + Python version |
| `hello.sh` | Bash | "Hello, World!" + shell info |
| `hello.rb` | Ruby | "Hello, World!" + Ruby version |
| `hello.go` | Go | "Hello, World!" + Go version |
| `Hello.java` | Java | "Hello, World!" + Java version |
| `hello.c` | GCC | "Hello, World!" + time |
| `hello.cpp` | G++ | "Hello, World!" + time |
| `hello.json` | N/A | "Non-executable file type" |
| `hello.yaml` | N/A | "Non-executable file type" |
| `hello.md` | N/A | "Non-executable file type" |

### 4. Troubleshooting

#### If Node.js fails:
- Check that the runner container is using `node:18-bullseye-slim`
- Verify the container has Node.js installed
- Check the capabilities endpoint returns `"node": true`

#### If Python fails:
- Verify Python is available in the runner container
- Check the capabilities endpoint returns `"python": true`

#### If other languages fail:
- Check the capabilities endpoint for the specific runtime
- Verify the runner container has the required tools installed

## Production Readiness Checklist

- [ ] All supported languages execute correctly
- [ ] Non-executable files show appropriate messages
- [ ] Run button appears/disappears based on file type
- [ ] Output appears in the output tab
- [ ] Error handling works for missing runtimes
- [ ] Capabilities detection works correctly
- [ ] Session switching maintains capabilities
- [ ] Terminal integration works with all runtimes

## Environment Variables

To customize the runner image, set:
```bash
VIBECODING_RUNNER_IMAGE=node:18-bullseye-slim
```

For a more comprehensive image with multiple runtimes:
```bash
VIBECODING_RUNNER_IMAGE=ubuntu:22.04
```

Then install runtimes in the container startup command.
