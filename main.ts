/**
 * this is the yeet functionality blocks
 */
//% color = #02f588 weight = 20000
//% groups = '["yeet1","yeet2"]'
namespace yeetus{

//% group ="yeet1"
//% block 
export function showMiddlePin(x:number, y:number): void
{
    led.plot(x,y)
}

}