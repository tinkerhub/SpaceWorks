import { Link } from "react-router-dom";

import { SpaceWorksLogo } from "./SpaceWorksLogo";

const linkClasses =
  "rounded-sm text-body-ui text-ink-secondary pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center underline-offset-4 transition-colors duration-180 ease-standard hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

// Shared public footer: the Space Works lockup, the About and License links, copyright.
export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="mt-auto border-t border-line bg-canvas">
      <div className="mx-auto flex max-w-[var(--sw-chrome-max,1200px)] flex-col gap-5 px-4 py-8 sm:px-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <Link to="/" aria-label="Open makerspace listing" className="inline-flex items-center self-start rounded-md text-ink pointer-coarse:min-h-11 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
            <SpaceWorksLogo size={24} withWordmark />
          </Link>
          <nav aria-label="Footer">
            <ul className="flex flex-wrap gap-x-6 gap-y-2">
              <li>
                <Link className={linkClasses} to="/about">
                  About
                </Link>
              </li>
              <li>
                <a
                  className={linkClasses}
                  href="https://github.com/SpaceWorks-HQ/SpaceWorks/blob/main/LICENSE"
                  target="_blank"
                  rel="noreferrer"
                >
                  License
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              </li>
            </ul>
          </nav>
        </div>
        <p className="border-t border-line pt-5 text-caption text-ink-muted">
          &copy; {year} Space Works &mdash; open source makerspace manager
        </p>
      </div>
    </footer>
  );
}
