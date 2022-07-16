/**
 * this is the yeet functionality blocks
 */
//% color = #02f588 weight = 200
//% groups = '["yeet1","yeet2"]'
namespace yeetus{

//% group ="yeet1"
//% block = "showMiddlePin"
export function showMiddlePin(x:number, y:number): void
{
    led.plot(x,y)
}

}