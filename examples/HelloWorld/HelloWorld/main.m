#import <Foundation/Foundation.h>

@interface Greeter : NSObject
- (void)sayHello:(NSString *)name;
- (NSInteger)add:(NSInteger)a to:(NSInteger)b;
@end

@implementation Greeter

- (void)sayHello:(NSString *)name {
    NSLog(@"Hello, %@!", name);
}

- (NSInteger)add:(NSInteger)a to:(NSInteger)b {
    NSInteger result = a + b;
    NSLog(@"%ld + %ld = %ld", (long)a, (long)b, (long)result);
    return result;
}

@end

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSLog(@"Starting HelloWorld...");

        Greeter *greeter = [[Greeter alloc] init];
        [greeter sayHello:@"World"];
        [greeter sayHello:@"LLDB"];

        NSInteger sum = [greeter add:42 to:58];
        NSLog(@"Sum is: %ld", (long)sum);

        NSLog(@"Done!");
    }
    return 0;
}
