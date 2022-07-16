/**
 * Custom blocks
 */
//% weight=10 color=#20bd93
//% groups = '["hello"]'
namespace evenNumberChecker {

    /**
     *  Checks if a number is even
     */
    //% blockID = CheckIfANumberIsEven
    //% block = "checkeven"
    //% group = "hello"
    export function checkEven(num: number): boolean {
        let result = false;
        let value = num % 2;
        if (value === 0) {
            result = true;
        }
        return result;
    }
}