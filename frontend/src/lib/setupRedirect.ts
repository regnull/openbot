/** Whether setup completion should take the user to the new-thread screen. */
export function shouldRedirectAfterSetup(wasIncomplete: boolean, complete: boolean): boolean {
  return wasIncomplete && complete;
}
