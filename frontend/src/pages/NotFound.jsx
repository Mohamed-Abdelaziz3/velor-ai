import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';

const NotFound = () => {
    return (
        <div dir="rtl" className="min-h-screen bg-velor-deep velor-grid-bg flex items-center justify-center px-4 relative overflow-hidden font-sans selection:bg-velor-purple/30">
            <div className="fixed top-0 left-1/2 -translate-x-1/2 w-full h-[600px] bg-velor-purple/5 blur-[150px] pointer-events-none" />

            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 300, damping: 24 }}
                className="relative z-10 text-center max-w-lg w-full"
            >
                <h1 className="text-[10rem] font-extrabold leading-none bg-gradient-to-r from-velor-violet to-velor-blue bg-clip-text text-transparent select-none">
                    404
                </h1>

                <h2 className="text-2xl font-bold text-white mb-4 -mt-4">
                    الصفحة غير موجودة
                </h2>

                <p className="text-velor-muted mb-10 leading-relaxed">
                    عذراً، الصفحة التي تبحث عنها غير موجودة أو تم نقلها إلى عنوان آخر.
                </p>

                <Link
                    to="/"
                    className="velor-button-primary px-8"
                >
                    <svg className="w-5 h-5 rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                    </svg>
                    العودة إلى الرئيسية
                </Link>
            </motion.div>
        </div>
    );
};

export default NotFound;
