import { chromium } from "playwright";
const url = "http://localhost:3000/"
console.log("came1");
export async function GET({email,password,post_id}) {
    console.log("came");
    const browser = await chromium.launch({headless : false})
    const page = await browser.newPage()
    await page.goto("https://google.com")
    await page.goto(
        `${url}login`
    );
    await page.fill(`input[type="email"]`,`${email}`)
    await page.fill('input[type="password"]',`${password}`)
    console.log("cme2")
    await page.click('button[type="submit"]')
    console.log("cme3")
    await page.waitForLoadState("networkidle")
    console.log(await page.title());
    await page.goto(`${url}Postprticulr/${post_id}`)
    await page.waitForTimeout(5000)
    await browser.close();
}

// Run from CLI
if (process.argv[1] && process.argv[1].endsWith('seepost.js')) {
    const email = process.argv[2];
    const password = process.argv[3];
    const post_id = process.argv[4];
    if (email && password !==null && post_id) {
        GET({email, password, post_id}).then(() => {
            console.log("Finished");
        }).catch(err => {
            console.error(err);
            process.exit(1);
        });
    } else {
        console.error("Missing arguments: email, password, post_id");
    }
}
