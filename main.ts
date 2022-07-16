/**
 * Custom blocks
 */
//% weight=10 color=#20bd93
namespace evenNumberChecker {

    /**
     *  Checks if a number is even
     */
    //% blockID = CheckIfANumberIsEven
    //% block = "checkeven"
    export function checkEven(num: number): boolean {
        let result = false;
        let value = num % 2;
        if (value === 0) {
            result = true;
        }
        return result;
    }
}