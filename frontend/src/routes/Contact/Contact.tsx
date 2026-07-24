import StaticPage from '../../components/StaticPage';

export default function Contact() {
  return <StaticPage titleKey="contact_title" bodyKeys={['contact_body1', 'contact_body2']} />;
}
