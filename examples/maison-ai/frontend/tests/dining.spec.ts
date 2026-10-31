import {test,expect} from '@playwright/test';
async function openChat(page:import('@playwright/test').Page){
 await page.getByRole('tab',{name:'Agent',exact:true}).click();
}
async function ask(page:import('@playwright/test').Page,text:string){
 await openChat(page);
 const input=page.getByTestId('copilot-chat-textarea');
 await input.fill(text);await input.press('Enter');
}
test('actual ADK tools render A2UI, add to server cart and confirm a demo order',async({page})=>{
 await page.goto('/');await expect(page.getByText('Mock Mode · scripted agent and UI fixtures. No live model generation.')).toBeVisible();
 await ask(page,'Show vegetarian dishes.');
 const surface=page.getByTestId('a2ui-surface').first();await expect(surface).toBeVisible();
 await expect(page.locator('#dining-chat [data-testid="a2ui-surface"]').first()).toBeVisible();
 await expect(page.locator('.dining-workspace')).toHaveCount(0);
 await expect(surface.getByRole('button',{name:'Add to cart'}).first()).toBeVisible();
 await surface.getByRole('button',{name:'Add to cart'}).first().click();
 await page.getByRole('button',{name:/Your table, \d+ items/}).click();
 await expect(page.getByRole('button',{name:'Checkout',exact:true})).toBeEnabled();
 const sid=await page.evaluate(()=>sessionStorage.getItem('maison-thread'));
 const cart=await page.request.get('/api/demo/cart/'+sid);expect((await cart.json()).count).toBe(1);
 await page.getByRole('button',{name:'Checkout',exact:true}).click();
 await expect(page.getByRole('button',{name:'Confirm Order',exact:true})).toBeVisible();
 expect(await (await page.request.get('/api/demo/orders/'+sid)).json()).toHaveLength(0);
 await page.getByRole('button',{name:'Confirm Order',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your order is in.'})).toBeVisible();
 expect(await (await page.request.get('/api/demo/orders/'+sid)).json()).toHaveLength(1);
 await openChat(page);await page.getByRole('button',{name:'Developer Inspector'}).click();
 await expect(page.getByRole('heading',{name:'Latest A2UI operations'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
test('ask_user resumes ADK with chosen steak doneness',async({page})=>{
 await page.goto('/');await ask(page,"I'd like a steak.");
 await page.getByRole('button',{name:'medium rare',exact:true}).click();
 await page.getByRole('button',{name:'Confirm choice'}).click();
 await expect(page.getByTestId('a2ui-surface').getByLabel('doneness')).toHaveValue('medium-rare');
});
