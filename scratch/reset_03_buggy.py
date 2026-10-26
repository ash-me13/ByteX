from pathlib import Path

CODE = """#include <iostream>
using namespace std;

int main() {
    int a = 10;
    int b = 20;
    int sum = a + b // Intentional compilation error: missing semicolon
    cout << "Sum: " << sum << endl;
    return 0;
}
"""

p = Path(r"C:\Users\ryzzn\OneDrive\Desktop\ByteX_Test_Lab\03_buggy.cpp")
p.write_text(CODE, encoding="utf-8")
print("Reset 03_buggy.cpp successfully.")
