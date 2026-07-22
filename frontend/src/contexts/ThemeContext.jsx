import { createContext, useContext, useEffect, useState } from 'react';

const ThemeContext = createContext();

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => {
    return useContext(ThemeContext);
};

export const ThemeProvider = ({ children }) => {
    // Enforce dark mode for Velor
    // eslint-disable-next-line unused-imports/no-unused-vars
    const [theme, setTheme] = useState('dark');

    useEffect(() => {
        const root = window.document.documentElement;
        root.classList.add('dark');
        localStorage.setItem('velor_theme', 'dark');
    }, []);

    const toggleTheme = () => {
        // Theme toggling is disabled, Velor is exclusively dark mode.
        console.warn('Velor is a dark-mode exclusive application.');
    };

    return (
        <ThemeContext.Provider value={{ theme, toggleTheme }}>
            {children}
        </ThemeContext.Provider>
    );
};

