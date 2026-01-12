#import <Foundation/Foundation.h>

// Same code as HelloWorld but will be compiled with heavy optimizations
// and stripped of symbols to test LLDB command robustness

@interface Greeter : NSObject {
    NSString *_greeting;
    NSDictionary *_metadata;
    NSInteger _count;
    NSDictionary *_nestedData;
}
- (void)sayHello:(NSString *)name;
- (NSInteger)add:(NSInteger)a to:(NSInteger)b;
@end

@implementation Greeter

- (instancetype)init {
    self = [super init];
    if (self) {
        _greeting = @"Hello";
        _count = 0;

        _nestedData = @{
            @"fruits": @[@"apple", @"banana", @"cherry", @"date", @"elderberry"],
            @"colors": @[@"red", @"green", @"blue", @"yellow", @"purple"],
            @"cities": @[@"Tokyo", @"Paris", @"London", @"Sydney", @"Cairo"]
        };

        _metadata = @{
            @"version": @"1.0",
            @"author": @"Test",
            @"nested": _nestedData
        };
    }
    return self;
}

- (void)sayHello:(NSString *)name {
    NSLog(@"Hello, %@!", name);
    NSLog(@"Nested data has %lu keys", (unsigned long)[_nestedData count]);
}

- (NSInteger)add:(NSInteger)a to:(NSInteger)b {
    NSInteger result = a + b;
    NSLog(@"%ld + %ld = %ld", (long)a, (long)b, (long)result);
    return result;
}

@end

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSLog(@"Starting HelloWorld (Optimised)...");

        Greeter *greeter = [[Greeter alloc] init];
        [greeter sayHello:@"World"];
        [greeter sayHello:@"LLDB"];

        NSInteger sum = [greeter add:42 to:58];
        NSLog(@"Sum is: %ld", (long)sum);

        NSLog(@"Done!");
    }
    return 0;
}
